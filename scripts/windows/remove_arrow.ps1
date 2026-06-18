<#
Hide (or restore) the desktop shortcut arrow overlay.

Disables the overlay by deleting the per-class `IsShortcut` marker on lnkfile and
piffile, then restarts Explorer. This is preferred over pointing overlay #29 at a
blank icon: with no overlay registered Explorer composites nothing onto shortcuts,
so a cold-boot icon-cache rebuild can't bake an opaque black square into the arrow
region (the classic "black square after reboot" bug). Reversible with -Restore.
Requires admin (HKLM). Also clears any legacy overlay-#29 override and the icon
cache so a previously-cached black square disappears immediately.

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

if ($Restore) {
    foreach ($k in $classKeys) {
        if (-not (Test-Path $k)) { New-Item -Path $k -Force | Out-Null }
        # Presence of IsShortcut (empty string) re-enables the overlay.
        Set-ItemProperty -Path $k -Name 'IsShortcut' -Value '' -Type String
    }
    Write-Log "restored IsShortcut markers (arrows shown)"
} else {
    foreach ($k in $classKeys) {
        if (Test-Path $k) {
            Remove-ItemProperty -Path $k -Name 'IsShortcut' -ErrorAction SilentlyContinue
        }
    }
    Write-Log "removed IsShortcut markers (arrows hidden)"
}

# Clean up any legacy overlay-#29 blank-icon override so the two methods don't fight.
$overlayKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (Test-Path $overlayKey) {
    Remove-ItemProperty -Path $overlayKey -Name '29' -ErrorAction SilentlyContinue
}

# Restart Explorer, clearing the icon cache while it is stopped so a stale
# black-square overlay can't survive the toggle.
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
