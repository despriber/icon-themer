param(
    [Parameter(Mandatory = $true)][string]$ShortcutPath,
    [Parameter(Mandatory = $true)][string]$IcoPath
)

if (-not (Test-Path $ShortcutPath)) { throw "Shortcut not found: $ShortcutPath" }
if (-not (Test-Path $IcoPath))      { throw "Icon not found: $IcoPath" }

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($ShortcutPath)
$lnk.IconLocation = "$IcoPath,0"
$lnk.Save()
Write-Output "Set icon: $ShortcutPath -> $IcoPath"

# Nudge the shell to refresh icon cache for this change.
Add-Type -Namespace Win32 -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
[Win32.Shell]::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)  # SHCNE_ASSOCCHANGED
Write-Output "Refreshed shell icon notification."
