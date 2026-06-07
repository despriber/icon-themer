<#
Enumerate desktop .lnk shortcuts (user + public) and, in one pass, dump each
shortcut's current displayed icon to a cache folder. Emits a JSON array to
-OutJson (UTF8 file, to dodge PS 5.1 console GBK issues).

Each record: Path, Name, Directory, TargetPath, IconLocation, WorkingDirectory, Thumb

Usage:
  powershell -File scripts\windows\scan_shortcuts.ps1 -OutJson out.json -CacheDir output\cache
#>
param(
    [Parameter(Mandatory = $true)][string]$OutJson,
    [Parameter(Mandatory = $true)][string]$CacheDir
)

Add-Type -AssemblyName System.Drawing

# Largest-icon extractor (SHIL_JUMBO) - same approach as scripts/windows/extract_icon.ps1,
# but called on the .lnk itself so custom icons are reflected.
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

if (-not (Test-Path $CacheDir)) { New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null }

$md5 = [System.Security.Cryptography.MD5]::Create()
function Hash-Path([string]$s) {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($s)
    ($md5.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join '' | ForEach-Object { $_.Substring(0,16) }
}

# Trim transparent border + center into a square thumbnail.
function Save-Thumb([System.Drawing.Bitmap]$bmp, [string]$outPng, [int]$size = 96) {
    $minX=$bmp.Width; $minY=$bmp.Height; $maxX=0; $maxY=0; $found=$false
    for ($y=0; $y -lt $bmp.Height; $y++) {
        for ($x=0; $x -lt $bmp.Width; $x++) {
            if ($bmp.GetPixel($x,$y).A -gt 8) { $found=$true
                if ($x -lt $minX){$minX=$x}; if ($x -gt $maxX){$maxX=$x}
                if ($y -lt $minY){$minY=$y}; if ($y -gt $maxY){$maxY=$y} }
        }
    }
    $src = $bmp
    if ($found) {
        $w = $maxX-$minX+1; $h = $maxY-$minY+1
        $crop = New-Object System.Drawing.Bitmap($w,$h)
        $g = [System.Drawing.Graphics]::FromImage($crop)
        $g.DrawImage($bmp, (New-Object System.Drawing.Rectangle(0,0,$w,$h)), (New-Object System.Drawing.Rectangle($minX,$minY,$w,$h)), [System.Drawing.GraphicsUnit]::Pixel)
        $g.Dispose(); $src = $crop
    }
    $canvas = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($canvas)
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $margin = [Math]::Max(1, [int][Math]::Round($size * 0.06))
    $maxGlyph = [Math]::Max(1, $size - ($margin * 2))
    $scale = [Math]::Min($maxGlyph / $src.Width, $maxGlyph / $src.Height)
    $dw = [Math]::Max(1, [int][Math]::Round($src.Width * $scale))
    $dh = [Math]::Max(1, [int][Math]::Round($src.Height * $scale))
    $dx = [int][Math]::Floor(($size - $dw) / 2)
    $dy = [int][Math]::Floor(($size - $dh) / 2)
    $g.DrawImage($src, (New-Object System.Drawing.Rectangle($dx, $dy, $dw, $dh)))
    $g.Dispose()
    $canvas.Save($outPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $canvas.Dispose()
    if ($src -ne $bmp) { $src.Dispose() }
}

$dirs = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('CommonDesktopDirectory')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$ws = New-Object -ComObject WScript.Shell
$records = @()

foreach ($dir in $dirs) {
    # Shortcuts (.lnk) and folders. Plain files are intentionally skipped:
    # Windows cannot give a single file its own icon (icon = file type).
    $items = @()
    $items += Get-ChildItem -LiteralPath $dir -Filter *.lnk -File -ErrorAction SilentlyContinue
    $items += Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue

    foreach ($it in $items) {
        $path = $it.FullName
        $isFolder = $it.PSIsContainer
        $type = if ($isFolder) { 'folder' } else { 'shortcut' }
        $target = ''; $iconLoc = ''; $workDir = ''
        if (-not $isFolder) {
            try {
                $lnk = $ws.CreateShortcut($path)
                $target = $lnk.TargetPath
                $iconLoc = $lnk.IconLocation
                $workDir = $lnk.WorkingDirectory
            } catch {}
        }

        $thumb = ''
        try {
            $bmp = [JumboIcon]::Get($path)
            $thumb = Join-Path $CacheDir ((Hash-Path $path) + '.png')
            Save-Thumb $bmp $thumb 96
            $bmp.Dispose()
        } catch { $thumb = '' }

        $records += [pscustomobject]@{
            Path             = $path
            Name             = $it.Name
            Directory        = $dir
            Type             = $type
            TargetPath       = $target
            IconLocation     = $iconLoc
            WorkingDirectory = $workDir
            Thumb            = $thumb
        }
    }
}

# Always emit a JSON array (wrap so a single record is not collapsed to an object).
$json = ConvertTo-Json -InputObject @($records) -Depth 4
[System.IO.File]::WriteAllText($OutJson, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Output ("scanned " + $records.Count + " shortcuts -> " + $OutJson)
