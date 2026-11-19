# Builds dist\Frameline.exe and dist\Stillframe.exe (single-file, no console). Run from this folder:
#   python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt ; .\build.ps1
#   .\build.ps1 -App Stillframe      # just one of them
param([string]$Python = ".\.venv\Scripts\python.exe", [ValidateSet("All", "Frameline", "Stillframe")][string]$App = "All")
& $Python build_assets\make_icon.py
$common = @("--noconfirm", "--clean", "--onefile", "--windowed", "--workpath", "build", "--specpath", "build",
            "--exclude-module", "tkinter", "--exclude-module", "matplotlib")
if ($App -in "All", "Frameline") {
    & $Python -m PyInstaller @common --name Frameline --icon "$PSScriptRoot\build_assets\frameline.ico" `
        --collect-binaries av --collect-data sounddevice --hidden-import sounddevice `
        --exclude-module PIL --exclude-module pillow_heif run.py
    Write-Host "Built dist\Frameline.exe"
}
if ($App -in "All", "Stillframe") {
    & $Python -m PyInstaller @common --name Stillframe --icon "$PSScriptRoot\build_assets\stillframe.ico" `
        --collect-binaries av --collect-binaries pillow_heif --hidden-import pillow_heif --hidden-import send2trash `
        --exclude-module sounddevice run_stillframe.py
    Write-Host "Built dist\Stillframe.exe"
}
