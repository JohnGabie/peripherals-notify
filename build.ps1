# build.ps1 — Build BatteryMonitor.exe
# Usage:
#   .\build.ps1           — build only
#   .\build.ps1 -Install  — build + install + launch

param(
    [switch]$Install
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
Set-Location $ProjectDir

# ── 1. Generate icon.ico ──────────────────────────────────────────────────────
Write-Host "Generating icon.ico..." -ForegroundColor Cyan
python make_icon.py
if ($LASTEXITCODE -ne 0) { Write-Error "Icon generation failed"; exit 1 }

# ── 2. Run PyInstaller ────────────────────────────────────────────────────────
Write-Host "`nBuilding EXE..." -ForegroundColor Cyan
pyinstaller BatteryMonitor.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

$ExePath = Join-Path $ProjectDir "dist\BatteryMonitor.exe"
$SizeMB  = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
Write-Host "`nBuild successful: $ExePath  ($SizeMB MB)" -ForegroundColor Green

# ── 3. Install (optional) ─────────────────────────────────────────────────────
if ($Install) {
    Write-Host "`nInstalling..." -ForegroundColor Cyan
    & $ExePath --install
} else {
    Write-Host @"

Next steps:
  Install :  .\dist\BatteryMonitor.exe --install
  Uninstall: .\dist\BatteryMonitor.exe --uninstall
  Update  :  .\build.ps1 -Install
"@ -ForegroundColor Yellow
}
