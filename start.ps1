# Menu del modulo de alertas (monitor, calibrar, API de suscriptores, mock, diagnostico)
Set-Location $PSScriptRoot
if (-not (Test-Path ".\venv\Scripts\python.exe")) { Write-Host "Primero ejecuta .\setup.ps1" -ForegroundColor Red; exit 1 }
& .\venv\Scripts\python.exe run.py
