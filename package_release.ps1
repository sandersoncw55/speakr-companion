# Automated Packaging & Release Script for Speakr Windows Companion
$ErrorActionPreference = "Stop"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Building Speakr Windows Companion Release" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 1. Run Test Suite
Write-Host "`n[1/4] Running test suite..." -ForegroundColor Yellow
$testOutput = & .venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed! Aborting release build."
    exit 1
}
Write-Host "[OK] All tests passed cleanly!" -ForegroundColor Green

# 2. Build Standalone Executable with PyInstaller
Write-Host "`n[2/4] Compiling standalone executable with PyInstaller..." -ForegroundColor Yellow
Stop-Process -Name "SpeakrCompanion" -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
& .venv\Scripts\pyinstaller.exe --clean SpeakrCompanion.spec
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed!"
    exit 1
}
Write-Host "[OK] Executable built: dist\SpeakrCompanion.exe" -ForegroundColor Green

# 3. Create Releases Directory & Portable ZIP
Write-Host "`n[3/4] Creating portable distribution package..." -ForegroundColor Yellow
$releaseDir = Join-Path $scriptDir "releases"
if (-not (Test-Path $releaseDir)) {
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
}

$tempPkgDir = Join-Path $releaseDir "SpeakrCompanion_Portable"
if (Test-Path $tempPkgDir) {
    Remove-Item -Path $tempPkgDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tempPkgDir -Force | Out-Null

Copy-Item "dist\SpeakrCompanion.exe" -Destination $tempPkgDir
Copy-Item "app_icon.ico" -Destination $tempPkgDir
Copy-Item "README.md" -Destination $tempPkgDir

$zipPath = Join-Path $releaseDir "SpeakrCompanion_Portable_v1.0.1.zip"
if (Test-Path $zipPath) {
    Remove-Item -Path $zipPath -Force
}
Compress-Archive -Path "$tempPkgDir\*" -DestinationPath $zipPath
Remove-Item -Path $tempPkgDir -Recurse -Force

Write-Host "[OK] Portable ZIP created: $zipPath" -ForegroundColor Green

# 4. Optional Inno Setup Compiler check
Write-Host "`n[4/4] Checking for Inno Setup compiler (ISCC)..." -ForegroundColor Yellow
$isccCmd = Get-Command iscc -ErrorAction SilentlyContinue
$isccPath = $null
if ($isccCmd) {
    $isccPath = $isccCmd.Source
} else {
    $possiblePaths = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($p in $possiblePaths) {
        if (Test-Path $p) {
            $isccPath = $p
            break
        }
    }
}

if ($isccPath) {
    Write-Host "Found Inno Setup at: $isccPath" -ForegroundColor Cyan
    Write-Host "Compiling setup installer..." -ForegroundColor Yellow
    & $isccPath "installer.iss"
    Write-Host "[OK] Setup installer created in releases\" -ForegroundColor Green
} else {
    Write-Host "Note: Inno Setup (ISCC) not found on PATH. To generate a standard installer wizard (.exe), install Inno Setup 6 and run: iscc installer.iss" -ForegroundColor DarkGray
}

Write-Host "`n=============================================" -ForegroundColor Cyan
Write-Host "Packaging Complete! Ready for distribution in releases\" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
