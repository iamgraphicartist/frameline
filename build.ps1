# Builds dist\Frameline.exe (single-file, no console). Run from this folder:
#   python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt ; .\build.ps1
param([string]$Python = ".\.venv\Scripts\python.exe")
& $Python build_assets\make_icon.py
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name Frameline --icon "$PSScriptRoot\build_assets\frameline.ico" `
    --collect-binaries av --collect-data sounddevice --hidden-import sounddevice `
    --exclude-module tkinter --exclude-module matplotlib `
    --workpath build --specpath build run.py
Write-Host "Built dist\Frameline.exe"
