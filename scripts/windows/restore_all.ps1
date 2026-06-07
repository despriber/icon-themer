<#
Full restore: undo ALL changes made by icon-themer back to original state.
  1) shortcut names  (from name_backup.json)
  2) custom icons    (IconLocation reset to default ",0")
  3) shortcut arrows (remove registry override)
Then restart Explorer. One UAC prompt (self-elevates).

Usage: powershell -File scripts\windows\restore_all.ps1
#>
param(
    [string]$Root,
    [string]$LogFile
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Root) { $Root = $ProjectRoot }

function Write-Log($msg) {
    Write-Output $msg
    if ($LogFile) { Add-Content -LiteralPath $LogFile -Value $msg -Encoding UTF8 }
}

# --- elevate once ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    $log = Join-Path $env:TEMP "restore_all_elevated.log"
    if (Test-Path $log) { Remove-Item $log -Force }
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$PSCommandPath`"",
                 '-Root', "`"$Root`"", '-LogFile', "`"$log`"")
    Write-Output "Requesting administrator (UAC prompt)..."
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    if (Test-Path $log) { Get-Content -LiteralPath $log -Encoding UTF8 }
    else { Write-Warning "Elevated run produced no log (cancelled?)." }
    return
}

$ws = New-Object -ComObject WScript.Shell

# 1) restore names ----------------------------------------------------------
$backupFile = Join-Path $Root "name_backup.json"
if (Test-Path $backupFile) {
    $entries = Get-Content $backupFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($e in $entries) {
        $current = Join-Path $e.Directory $e.HiddenName
        try {
            if (Test-Path -LiteralPath $current) {
                Rename-Item -LiteralPath $current -NewName $e.OriginalName -Force
                Write-Log "[name] restored: $($e.OriginalName)"
            } else {
                Write-Log "[name] already original: $($e.OriginalName)"
            }
        } catch { Write-Log "[name] WARN $($e.OriginalName): $($_.Exception.Message)" }
    }
} else { Write-Log "[name] no name_backup.json, skipping" }

# 2) reset custom icons to default -----------------------------------------
$appsFile = Join-Path $Root "apps.json"
if (Test-Path $appsFile) {
    $apps = (Get-Content $appsFile -Raw -Encoding UTF8 | ConvertFrom-Json).apps
    foreach ($a in $apps) {
        try {
            if (Test-Path -LiteralPath $a.shortcut) {
                $lnk = $ws.CreateShortcut($a.shortcut)
                $lnk.IconLocation = ",0"
                $lnk.Save()
                Write-Log "[icon] reset to default: $($a.display_name)"
            } else { Write-Log "[icon] shortcut missing: $($a.shortcut)" }
        } catch { Write-Log "[icon] WARN $($a.display_name): $($_.Exception.Message)" }
    }
} else { Write-Log "[icon] no apps.json, skipping" }

# 3) restore shortcut arrows ------------------------------------------------
$key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (Test-Path $key) {
    Remove-ItemProperty -Path $key -Name '29' -ErrorAction SilentlyContinue
    Write-Log "[arrow] overlay override removed"
} else { Write-Log "[arrow] no override present" }

# restart explorer to apply all of the above
try {
    Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Start-Process explorer
    Write-Log "explorer restarted - all changes reverted to original"
} catch { Write-Log "WARN explorer restart: $($_.Exception.Message)" }
