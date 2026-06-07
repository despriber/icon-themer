<#
Set a shortcut's IconLocation to a raw string (no file validation), then
refresh the shell. Used for restore, where the original value may be ",0"
(meaning: derive the icon from the target) rather than a real file path.

Usage:
  powershell -File scripts\windows\set_icon.ps1 -ShortcutPath x.lnk -IconLocation ",0"
#>
param(
    [Parameter(Mandatory = $true)][string]$ShortcutPath,
    [Parameter(Mandatory = $true)][AllowEmptyString()][string]$IconLocation
)

if (-not (Test-Path -LiteralPath $ShortcutPath)) { throw "Shortcut not found: $ShortcutPath" }

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($ShortcutPath)
if (-not $IconLocation) { $IconLocation = ",0" }
$lnk.IconLocation = $IconLocation
$lnk.Save()
Write-Output "Set IconLocation: $ShortcutPath -> $IconLocation"

Add-Type -Namespace Win32 -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
[Win32.Shell]::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)
