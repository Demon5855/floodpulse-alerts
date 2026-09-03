# FloodPulse Alertas - instalacion en Windows
# Ejecutar desde esta carpeta:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== FloodPulse Alertas: instalacion ==" -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host "No se encontro 'python' en el PATH." -ForegroundColor Red; exit 1 }
python --version

if (-not (Test-Path ".\venv")) { python -m venv venv }
& .\venv\Scripts\python.exe -m pip install --upgrade pip
& .\venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path ".\.env")) {
    # .env de desarrollo: se parte de .env.example y se rellenan los placeholders.
    # API_KEY debe coincidir con PUBLIC_SUBS_API_KEY en floodpulse-frontend/.env
    (Get-Content .env.example) `
        -replace 'http://\[TERMUX_IP_ADDRESS\]', 'http://192.168.1.50:8080' `
        -replace '\[Inserte Contrase.a\]', 'floodpulse-gateway-demo' `
        -replace 'pon-aqui-una-clave-compartida-con-el-dashboard', 'floodpulse-dev-key' |
        Set-Content .env -Encoding UTF8
    Write-Host "Se creo .env (API_KEY=floodpulse-dev-key). Ajusta GATEWAY_URL/GATEWAY_TOKEN cuando tengas el celular con Termux." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Listo. Arranca con:  .\start.ps1   (menu: python run.py)" -ForegroundColor Green
