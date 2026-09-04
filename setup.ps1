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
    # .env de desarrollo: se parte de .env.example y se generan claves
    # aleatorias (nunca fijas, porque este script es publico en el repo).
    # API_KEY debe coincidir con PUBLIC_SUBS_API_KEY en floodpulse-frontend/.env
    $gatewayToken = [guid]::NewGuid().ToString("N").Substring(0, 16)
    $apiKey = [guid]::NewGuid().ToString("N").Substring(0, 16)

    (Get-Content .env.example) `
        -replace 'GATEWAY_TOKEN=.*', "GATEWAY_TOKEN=$gatewayToken" `
        -replace 'API_KEY=.*', "API_KEY=$apiKey" |
        Set-Content .env -Encoding UTF8

    Write-Host "Se creo .env con GATEWAY_TOKEN y API_KEY generados al azar." -ForegroundColor Yellow
    Write-Host "  GATEWAY_TOKEN=$gatewayToken  (usar el mismo valor con 'export GATEWAY_TOKEN=...' en Termux)" -ForegroundColor Yellow
    Write-Host "Ajusta GATEWAY_URL cuando tengas la IP del celular con Termux corriendo." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Listo. Arranca con:  .\start.ps1   (menu: python run.py)" -ForegroundColor Green
