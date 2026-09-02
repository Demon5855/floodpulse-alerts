"""
API de riesgo FALSA - solo para probar alerta_sms.py sin el backend real.
Imita la respuesta de /risk de FloodPulse.

    pip install flask
    python mock_risk_api.py      -> http://localhost:8000

En el .env de pruebas: API_BASE=http://localhost:8000
Cuando la Persona 1 te pase su URL (ngrok), cambias API_BASE y ya.
"""

from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# Parte estatica simulada por sector (TWI + cauce + impermeabilizacion).
# En el backend real esto lo calcula del terreno; aca lo fijamos para probar.
BASE_POR_SECTOR = {
    "0.35502,-78.12463": 48.0,   # Ajavi: pegado al cauce, urbano
    "-3.994537,-79.205415": 35.0,  # Malacatos
}


@app.route("/risk")
def risk():
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))
    rainfall_mm = float(request.args.get("rainfall_mm", 0))

    clave = f"{lat},{lon}"
    base = BASE_POR_SECTOR.get(clave, 40.0)

    # Misma normalizacion que el backend real: la lluvia satura en 25mm
    # y pesa 40% del score.
    rain_norm = min(rainfall_mm / 25.0, 1.0)
    score = round(base + rain_norm * 40.0, 2)

    return jsonify({
        "lat": lat,
        "lon": lon,
        "risk_score": score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": {
            "rainfall_mm": rainfall_mm,
            "twi_max": 12.4,
            "distance_to_channel_m": 85.0,
            "imperviousness_pct": 62.0,
        },
        "grid_geojson": {"type": "FeatureCollection", "features": []},
    })


if __name__ == "__main__":
    app.run(port=8000)