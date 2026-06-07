<#
Hide desktop shortcut labels (show icon only). Uses non-breaking space U+00A0
as a blank name (Windows does not trim it), incremented per file to stay unique.
Reversible via -Restore. Auto-elevates because Public Desktop shortcuts need admin.

Usage:
  powershell -File scripts\windows\hide_names.ps1                 # hide names from apps.json shortcuts
  powershell -File scripts\windows\hide_names.ps1 -Restore        # restore original names
#>
param(
    [switch]$Restore,
    [string]$BackupFile,
    [string[]]$Shortcuts,
    [string]$LogFile     # internal: used when relaunched elevated
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $BackupFile) { $BackupFile = Join-Path $ProjectRoot "name_backup.json" }

function Write-Log($msg) {
    Write-Output $msg
    if ($LogFile) { Add-Content -LiteralPath $LogFile -Value $msg -Encoding UTF8 }
}

# --- Elevate if not admin (renaming Public Desktop requires it) ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    $log = Join-Path $env:TEMP "hide_names_elevated.log"
    if (Test-Path $log) { Remove-Item $log -Force }
    $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File', "`"$PSCommandPath`"",
                 '-BackupFile', "`"$BackupFile`"", '-LogFile', "`"$log`"")
    if ($Restore) { $argList += '-Restore' }
    Write-Output "Requesting administrator (UAC prompt)..."
    Start-Process powershell -Verb RunAs -ArgumentList $argList -Wait
    if (Test-Path $log) { Get-Content -LiteralPath $log -Encoding UTF8 }
    else { Write-Warning "Elevated run produced no log (cancelled?)." }
    return
}

$NBSP = [char]0x00A0

if ($Restore) {
    if (-not (Test-Path $BackupFile)) { throw "Backup file not found: $BackupFile" }
    $entries = Get-Content $BackupFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($e in $entries) {
        $current = Join-Path $e.Directory $e.HiddenName
        $orig = Join-Path $e.Directory $e.OriginalName
        try {
            if (Test-Path -LiteralPath $current) {
                Rename-Item -LiteralPath $current -NewName $e.OriginalName -Force
                Write-Log "restored: $($e.OriginalName)"
            } elseif (Test-Path -LiteralPath $orig) {
                Write-Log "already original: $($e.OriginalName)"
            } else {
                Write-Log "WARN not found: $current"
            }
        } catch {
            Write-Log "WARN restore failed [$($e.OriginalName)]: $($_.Exception.Message)"
        }
    }
    return
}

# --- hide mode ---
if (-not $Shortcuts -or $Shortcuts.Count -eq 0) {
    $appsFile = Join-Path $ProjectRoot "apps.json"
    $Shortcuts = (Get-Content $appsFile -Raw -Encoding UTF8 | ConvertFrom-Json).apps.shortcut
}

$backup = @()
$i = 0
foreach ($path in $Shortcuts) {
    if (-not (Test-Path -LiteralPath $path)) { Write-Log "skip (missing): $path"; continue }
    $i++
    $dir = [System.IO.Path]::GetDirectoryName($path)
    $name = [System.IO.Path]::GetFileName($path)
    $hidden = ($NBSP.ToString() * $i) + ".lnk"
    try {
        Rename-Item -LiteralPath $path -NewName $hidden -Force
        $backup += [pscustomobject]@{ Directory = $dir; OriginalName = $name; HiddenName = $hidden }
        Write-Log "hidden: $name  ->  [blank x$i]"
    } catch {
        Write-Log "WARN failed [$name]: $($_.Exception.Message)"
    }
}

if ($backup.Count -gt 0) {
    $backup | ConvertTo-Json -Depth 3 | Out-File $BackupFile -Encoding UTF8
    Write-Log "backed up original names to: $BackupFile  (restore: powershell -File scripts\windows\hide_names.ps1 -Restore)"
}
