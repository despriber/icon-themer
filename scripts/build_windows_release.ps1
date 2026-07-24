param(
    [string]$Version = "v0.1.2",
    [string]$Python = "python",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$distRoot = Join-Path $repoRoot "dist"
$buildRoot = Join-Path $repoRoot "build"
$workRoot = Join-Path $buildRoot "release"
$builtDir = Join-Path $distRoot "IconThemer"
$packageName = "IconThemer-$Version-windows-x64"
$packageDir = Join-Path $distRoot $packageName
$zipPath = Join-Path $distRoot "$packageName.zip"

Set-Location $repoRoot

if (-not $SkipInstall) {
    & $Python -m pip install -r requirements.txt -r requirements-build.txt
}

foreach ($path in @($builtDir, $packageDir, $zipPath, $workRoot)) {
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name IconThemer `
    --workpath $workRoot `
    --paths (Join-Path $repoRoot "src") `
    app.py

if (-not (Test-Path (Join-Path $builtDir "IconThemer.exe"))) {
    throw "PyInstaller did not create IconThemer.exe"
}

New-Item -ItemType Directory -Force -Path $packageDir | Out-Null
Copy-Item -Path (Join-Path $builtDir "*") -Destination $packageDir -Recurse -Force

foreach ($dir in @("assets", "themes")) {
    Copy-Item -Path (Join-Path $repoRoot $dir) -Destination (Join-Path $packageDir $dir) -Recurse -Force
}
Copy-Item `
    -Path (Join-Path $repoRoot "scripts\windows") `
    -Destination (Join-Path $packageDir "scripts\windows") `
    -Recurse -Force

foreach ($file in @("README.md", "LICENSE")) {
    Copy-Item -Path (Join-Path $repoRoot $file) -Destination (Join-Path $packageDir $file) -Force
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path $packageDir -DestinationPath $zipPath -Force

Write-Host "Built $zipPath"
