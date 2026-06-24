<#
Hide (or restore) the desktop shortcut arrow overlay.

Hides arrows by pointing overlay #29 (HKLM ``Shell Icons``) at a fully-transparent
icon, so Explorer composites nothing visible onto shortcuts while STILL treating
them as shortcuts. It never touches ``IsShortcut`` except to ensure it is present:
deleting that marker (an older approach) hides the arrow but breaks double-click
launching on Win11 ("no app associated with this file"). Ensuring IsShortcut here
also self-heals any machine left broken by that older version.

The overlay icon is written with classic DIB/BMP frames at small overlay sizes and
stored at a stable machine path. Crucially it is NOT fully transparent: one corner
pixel is left with alpha 1 (invisible on screen). A *fully* transparent overlay is
what Windows corrupts to a "black square in the corner" when it rebuilds the overlay
image list cold (every boot, and for newly-created shortcuts); a single non-blank
pixel makes Windows treat the icon as a real bitmap and honour its alpha instead.
Reversible with -Restore. Requires admin (HKLM).

Usage:
  powershell -File scripts\windows\remove_arrow.ps1            # hide arrows
  powershell -File scripts\windows\remove_arrow.ps1 -Restore   # bring arrows back
#>
param(
    [switch]$Restore,
    [string]$LogFile
)

function Write-Log($msg) {
    Write-Output $msg
    if ($LogFile) { Add-Content -LiteralPath $LogFile -Value $msg -Encoding UTF8 }
}

# --- elevate if needed (HKLM write) ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    $log = Join-Path $env:TEMP "remove_arrow_elevated.log"
    if (Test-Path $log) { Remove-Item $log -Force }
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$PSCommandPath`"",
                 '-LogFile', "`"$log`"")
    if ($Restore) { $argList += '-Restore' }
    Write-Output "Requesting administrator (UAC prompt)..."
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    if (Test-Path $log) { Get-Content -LiteralPath $log -Encoding UTF8 }
    else { Write-Warning "Elevated run produced no log (cancelled?)." }
    return
}

$classKeys = @(
    'HKLM:\SOFTWARE\Classes\lnkfile',
    'HKLM:\SOFTWARE\Classes\piffile'
)
$overlayKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
$overlayIco = Join-Path $env:ProgramData 'icon-themer\blank_overlay_v2.ico'
$legacyIco  = Join-Path $env:ProgramData 'icon-themer\blank_overlay.ico'

# Always keep IsShortcut present so .lnk launching keeps working (and heal machines
# broken by the old "delete IsShortcut" approach).
function Set-IsShortcut {
    foreach ($k in $classKeys) {
        if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
        Set-ItemProperty -Path $k -Name 'IsShortcut' -Value '' -Type String
    }
}

# Build a near-transparent multi-size .ico with classic DIB/BMP frames (32bpp). Every
# pixel is transparent EXCEPT one corner pixel (alpha 1, invisible): a fully
# transparent overlay is what Windows corrupts to an opaque black square on a cold
# overlay rebuild, so the single non-blank pixel is what actually prevents it.
function New-TransparentIco([string]$Path, [int[]]$Sizes) {
    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter($ms)
    # ICONDIR
    $bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$Sizes.Count)
    # image payloads, and remember each size so we can fill offsets afterwards
    $images = @()
    foreach ($s in $Sizes) {
        $im = New-Object System.IO.MemoryStream
        $iw = New-Object System.IO.BinaryWriter($im)
        # BITMAPINFOHEADER (height doubled: XOR + AND masks)
        $iw.Write([UInt32]40); $iw.Write([Int32]$s); $iw.Write([Int32]($s * 2))
        $iw.Write([UInt16]1); $iw.Write([UInt16]32); $iw.Write([UInt32]0)
        $iw.Write([UInt32]0); $iw.Write([Int32]0); $iw.Write([Int32]0)
        $iw.Write([UInt32]0); $iw.Write([UInt32]0)
        # XOR pixels: BGRA all zero EXCEPT the bottom-right pixel's alpha = 1, so the
        # icon is not "fully transparent" (which Windows corrupts to a black square).
        # DIB rows are bottom-up, so file row 0 is the bottom display row.
        $xor = New-Object byte[] ($s * $s * 4)
        $xor[(($s - 1) * 4) + 3] = 1
        $iw.Write($xor)
        # AND mask: rows padded to 4 bytes; 1 = transparent. Clear the bit for that
        # same bottom-right pixel (0 = opaque) so legacy GDI paths also see content.
        $rowBytes = [int][Math]::Ceiling($s / 32.0) * 4
        $andMask = New-Object byte[] ($rowBytes * $s)
        for ($i = 0; $i -lt $andMask.Length; $i++) { $andMask[$i] = 0xFF }
        $col = $s - 1
        $clear = (-bnot (0x80 -shr ($col % 8))) -band 0xFF
        $andMask[[int][Math]::Floor($col / 8)] = $andMask[[int][Math]::Floor($col / 8)] -band $clear
        $iw.Write($andMask)
        $iw.Flush()
        $images += ,@{ Size = $s; Bytes = $im.ToArray() }
    }
    # ICONDIRENTRY table follows the header; image data follows the table.
    $offset = 6 + (16 * $Sizes.Count)
    foreach ($img in $images) {
        $s = $img.Size
        $bw.Write([byte]($(if ($s -ge 256) { 0 } else { $s })))  # 0 means 256
        $bw.Write([byte]($(if ($s -ge 256) { 0 } else { $s })))
        $bw.Write([byte]0); $bw.Write([byte]0)
        $bw.Write([UInt16]1); $bw.Write([UInt16]32)
        $bw.Write([UInt32]$img.Bytes.Length); $bw.Write([UInt32]$offset)
        $offset += $img.Bytes.Length
    }
    foreach ($img in $images) { $bw.Write($img.Bytes) }
    $bw.Flush()
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    [System.IO.File]::WriteAllBytes($Path, $ms.ToArray())
}

Set-IsShortcut

if ($Restore) {
    if (Test-Path $overlayKey) {
        Remove-ItemProperty -Path $overlayKey -Name '29' -ErrorAction SilentlyContinue
    }
    Write-Log "restored: IsShortcut ensured, overlay #29 removed (arrows shown)"
} else {
    # Always (re)build so machines still carrying the old fully-transparent overlay
    # (which corrupts to a black square) are upgraded to the one-pixel icon.
    New-TransparentIco -Path $overlayIco -Sizes @(16, 20, 24, 32, 40, 48)
    if (Test-Path $legacyIco) { Remove-Item $legacyIco -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path $overlayKey)) { New-Item -Path $overlayKey -Force | Out-Null }
    Set-ItemProperty -Path $overlayKey -Name '29' -Value $overlayIco -Type String
    Write-Log "hidden: overlay #29 -> one-pixel icon, IsShortcut kept (arrows hidden)"
}

# Restart Explorer, clearing the icon cache while it is stopped so a stale overlay
# can't survive the toggle.
try {
    Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    $cache = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'
    if (Test-Path $cache) {
        Get-ChildItem -Path $cache -Filter 'iconcache_*.db' -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    Start-Process explorer
    Write-Log "explorer restarted (icon cache cleared)"
} catch {
    Write-Log "WARN could not restart explorer: $($_.Exception.Message)"
}
