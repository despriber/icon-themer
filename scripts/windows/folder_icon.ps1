<#
Set or clear a custom icon on a desktop folder via desktop.ini.

Set (default):
  powershell -File scripts\windows\folder_icon.ps1 -FolderPath "C:\...\MyFolder" -IcoPath "C:\...\icon.ico"
Clear:
  powershell -File scripts\windows\folder_icon.ps1 -FolderPath "C:\...\MyFolder" -Clear

A folder gets a custom icon when it (a) has the system attribute set and
(b) contains a desktop.ini with [.ShellClassInfo] IconResource=<ico>,0.
We write the .ini as a hidden+system file (so it stays invisible) and nudge
the shell to refresh the changed pidl.
#>
param(
    [Parameter(Mandatory = $true)][string]$FolderPath,
    [string]$IcoPath,
    [switch]$Clear
)

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ShellRefresh {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int wEventId, uint uFlags, IntPtr dwItem1, IntPtr dwItem2);
    public static void Update(string path) {
        // SHCNE_UPDATEITEM=0x2000, SHCNE_UPDATEDIR=0x1000, SHCNF_PATHW=0x0005
        IntPtr p = Marshal.StringToHGlobalUni(path);
        SHChangeNotify(0x00002000, 0x0005, p, IntPtr.Zero);
        SHChangeNotify(0x00001000, 0x0005, p, IntPtr.Zero);
        Marshal.FreeHGlobal(p);
        SHChangeNotify(0x08000000, 0x0000, IntPtr.Zero, IntPtr.Zero); // SHCNE_ASSOCCHANGED
    }
}
'@

if (-not (Test-Path -LiteralPath $FolderPath)) {
    Write-Error "folder not found: $FolderPath"; exit 1
}

$ini = Join-Path $FolderPath "desktop.ini"

if ($Clear) {
    if (Test-Path -LiteralPath $ini) {
        # drop hidden/system so we can delete, then remove
        attrib -h -s $ini 2>$null
        Remove-Item -LiteralPath $ini -Force -ErrorAction SilentlyContinue
    }
    # remove the system attribute from the folder so it stops looking for the .ini
    attrib -s $FolderPath 2>$null
} else {
    if (-not $IcoPath -or -not (Test-Path -LiteralPath $IcoPath)) {
        Write-Error "icon not found: $IcoPath"; exit 1
    }
    $abs = (Resolve-Path -LiteralPath $IcoPath).Path
    $content = "[.ShellClassInfo]`r`nIconResource=$abs,0`r`nConfirmFileOp=0`r`n"
    # clear any existing hidden/system attr so we can overwrite
    if (Test-Path -LiteralPath $ini) { attrib -h -s $ini 2>$null }
    [System.IO.File]::WriteAllText($ini, $content, (New-Object System.Text.UTF8Encoding($false)))
    # desktop.ini must be hidden+system; the folder itself must be system (or read-only)
    attrib +h +s $ini
    attrib +s $FolderPath
}

[ShellRefresh]::Update($FolderPath)
$verb = if ($Clear) { "cleared" } else { "set" }
Write-Output ("folder icon " + $verb + " -> " + $FolderPath)
