<#
Hide (or restore) the desktop shortcut arrow overlay.

Hides arrows by pointing overlay #29 (HKLM ``Shell Icons``) at a fully-transparent
icon, so Explorer composites nothing visible onto shortcuts while STILL treating
them as shortcuts. It never touches ``IsShortcut`` except to ensure it is present:
deleting that marker (an older approach) hides the arrow but breaks double-click
launching on Win11 ("no app associated with this file"). Ensuring IsShortcut here
also self-heals any machine left broken by that older version.

The transparent icon is written with classic DIB/BMP frames at small overlay sizes
and stored at a stable machine path, which avoids the "black square in the corner"
failure (caused by PNG-encoded or missing overlay icons). Reversible with -Restore.
Requires admin (HKLM).

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
$overlayIco = Join-Path $env:ProgramData 'icon-themer\blank_overlay.ico'

# Always keep IsShortcut present so .lnk launching keeps working (and heal machines
# broken by the old "delete IsShortcut" approach).
function Set-IsShortcut {
    foreach ($k in $classKeys) {
        if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
        Set-ItemProperty -Path $k -Name 'IsShortcut' -Value '' -Type String
    }
}

# Build a fully-transparent multi-size .ico with classic DIB/BMP frames (32bpp, zero
# alpha + all-transparent AND mask). DIB frames — not PNG — are what the overlay
# compositor renders reliably, so no opaque black square appears.
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
        # XOR pixels: BGRA all zero (fully transparent)
        $iw.Write((New-Object byte[] ($s * $s * 4)))
        # AND mask: rows padded to 4 bytes; 1 = transparent
        $rowBytes = [int][Math]::Ceiling($s / 32.0) * 4
        $andMask = New-Object byte[] ($rowBytes * $s)
        for ($i = 0; $i -lt $andMask.Length; $i++) { $andMask[$i] = 0xFF }
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
    if (-not (Test-Path $overlayIco)) {
        New-TransparentIco -Path $overlayIco -Sizes @(16, 20, 24, 32, 40, 48)
    }
    if (-not (Test-Path $overlayKey)) { New-Item -Path $overlayKey -Force | Out-Null }
    Set-ItemProperty -Path $overlayKey -Name '29' -Value $overlayIco -Type String
    Write-Log "hidden: overlay #29 -> transparent icon, IsShortcut kept (arrows hidden)"
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
