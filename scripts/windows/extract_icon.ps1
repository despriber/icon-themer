param(
    [Parameter(Mandatory = $true)][string]$Source,   # .exe or .lnk
    [Parameter(Mandatory = $true)][string]$OutPng,
    [int]$Size = 256
)

# Resolve a .lnk to its target exe for icon extraction.
$target = $Source
if ($Source.ToLower().EndsWith('.lnk')) {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($Source)
    if ($lnk.TargetPath) { $target = $lnk.TargetPath }
}
if (-not (Test-Path $target)) { throw "Target not found: $target" }

Add-Type -AssemblyName System.Drawing

# Pull the largest icon from the system "jumbo" image list (up to 256px).
$sig = @'
using System;
using System.Drawing;
using System.Runtime.InteropServices;
public static class JumboIcon {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)]
    struct SHFILEINFO { public IntPtr hIcon; public int iIcon; public uint dwAttributes;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string szDisplayName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=80)]  public string szTypeName; }
    [DllImport("shell32.dll")] static extern IntPtr SHGetFileInfo(string p, uint a, ref SHFILEINFO i, uint c, uint f);
    [DllImport("shell32.dll")] static extern int SHGetImageList(int iImageList, ref Guid riid, out IImageList ppv);
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr h);
    [ComImport, Guid("46EB5926-582E-4017-9FDF-E8998DAA0950"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IImageList { [PreserveSig] int Add(IntPtr a, IntPtr b, ref int i);
        [PreserveSig] int ReplaceIcon(int i, IntPtr h, ref int n);
        [PreserveSig] int SetOverlayImage(int i, int o);
        [PreserveSig] int Replace(int i, IntPtr a, IntPtr b);
        [PreserveSig] int AddMasked(IntPtr a, int m, ref int i);
        [PreserveSig] int Draw(IntPtr p); [PreserveSig] int Remove(int i);
        [PreserveSig] int GetIcon(int i, int flags, ref IntPtr picon); }
    public static Bitmap Get(string path) {
        var info = new SHFILEINFO();
        SHGetFileInfo(path, 0, ref info, (uint)Marshal.SizeOf(info), 0x000000100 | 0x000004000); // ICON|SYSICONINDEX
        var guid = new Guid("46EB5926-582E-4017-9FDF-E8998DAA0950");
        IImageList list; SHGetImageList(0x4, ref guid, out list); // SHIL_JUMBO
        IntPtr h = IntPtr.Zero; list.GetIcon(info.iIcon, 0x00000001, ref h); // ILD_TRANSPARENT
        var bmp = (Bitmap)Bitmap.FromHicon(h).Clone();
        DestroyIcon(h);
        return bmp;
    }
}
'@
Add-Type -TypeDefinition $sig -ReferencedAssemblies System.Drawing

$bmp = [JumboIcon]::Get($target)

# Jumbo bitmap is 256x256 but the glyph may sit top-left; trim transparent border.
$rect = New-Object System.Drawing.Rectangle(0,0,$bmp.Width,$bmp.Height)
$minX=$bmp.Width; $minY=$bmp.Height; $maxX=0; $maxY=0; $found=$false
for ($y=0; $y -lt $bmp.Height; $y++) {
  for ($x=0; $x -lt $bmp.Width; $x++) {
    if ($bmp.GetPixel($x,$y).A -gt 8) { $found=$true
      if ($x -lt $minX){$minX=$x}; if ($x -gt $maxX){$maxX=$x}
      if ($y -lt $minY){$minY=$y}; if ($y -gt $maxY){$maxY=$y} }
  }
}
if ($found) {
  $w = $maxX-$minX+1; $h = $maxY-$minY+1
  $crop = New-Object System.Drawing.Bitmap($w,$h)
  $g = [System.Drawing.Graphics]::FromImage($crop)
  $g.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0,0,$w,$h)), (New-Object System.Drawing.Rectangle($minX,$minY,$w,$h)), [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  $bmp.Dispose(); $bmp = $crop
}

# Re-pad to a centered transparent square at the requested size.
$canvas = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($canvas)
$g.Clear([System.Drawing.Color]::Transparent)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

$margin = [Math]::Max(1, [int][Math]::Round($Size * 0.06))
$maxGlyph = [Math]::Max(1, $Size - ($margin * 2))
$scale = [Math]::Min($maxGlyph / $bmp.Width, $maxGlyph / $bmp.Height)
$drawW = [Math]::Max(1, [int][Math]::Round($bmp.Width * $scale))
$drawH = [Math]::Max(1, [int][Math]::Round($bmp.Height * $scale))
$drawX = [int][Math]::Floor(($Size - $drawW) / 2)
$drawY = [int][Math]::Floor(($Size - $drawH) / 2)
$g.DrawImage($bmp, (New-Object System.Drawing.Rectangle($drawX, $drawY, $drawW, $drawH)))
$g.Dispose()
$bmp.Dispose()
$bmp = $canvas

$outDir = Split-Path $OutPng -Parent
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }
$bmp.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "Saved $OutPng ($($bmp.Width)x$($bmp.Height)) from $target"
$bmp.Dispose()
