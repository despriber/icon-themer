<#
Hide (or restore) the desktop shortcut arrow overlay.
Points Explorer's shortcut-overlay icon (resource 29) at a transparent .ico,
then restarts Explorer. Reversible with -Restore. Requires admin (HKLM).

Usage:
  powershell -File scripts\windows\remove_arrow.ps1            # hide arrows
  powershell -File scripts\windows\remove_arrow.ps1 -Restore   # bring arrows back
#>
param(
    [switch]$Restore,
    [string]$BlankIcon,
    [string]$LogFile
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $BlankIcon) { $BlankIcon = Join-Path $ProjectRoot "assets\blank.ico" }

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
                 '-BlankIcon', "`"$BlankIcon`"", '-LogFile', "`"$log`"")
    if ($Restore) { $argList += '-Restore' }
    Write-Output "Requesting administrator (UAC prompt)..."
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    if (Test-Path $log) { Get-Content -LiteralPath $log -Encoding UTF8 }
    else { Write-Warning "Elevated run produced no log (cancelled?)." }
    return
}

$key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'

if ($Restore) {
    if (Test-Path $key) {
        Remove-ItemProperty -Path $key -Name '29' -ErrorAction SilentlyContinue
        Write-Log "removed overlay override (arrows restored)"
    } else {
        Write-Log "no override present"
    }
} else {
    if (-not (Test-Path $BlankIcon)) { throw "Blank icon not found: $BlankIcon" }
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    # value format: "<path>,<index>"
    Set-ItemProperty -Path $key -Name '29' -Value ("$BlankIcon,0") -Type String
    Write-Log "set overlay 29 -> $BlankIcon (arrows hidden)"
}

# Rebuild icon cache and restart Explorer so the change shows immediately.
try {
    Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Start-Process explorer
    Write-Log "explorer restarted"
} catch {
    Write-Log "WARN could not restart explorer: $($_.Exception.Message)"
}
