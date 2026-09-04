"""
Gateway SMS local - corre EN EL CELULAR (Termux)
FloodPulse

Convierte un Android en gateway de SMS: recibe un POST y manda el mensaje
por el chip del telefono. No depende de Twilio ni de internet: solo de que
la laptop y el celular esten en la misma red (o en el hotspot del celular).

Instalacion en Termux (F-Droid, no Play Store):
    pkg update && pkg install python termux-api
    pip install flask
    termux-sms-send -n +593XXXXXXXXX "prueba"    # acepta el permiso de SMS

Correr:
    export GATEWAY_TOKEN="tu-clave"   # la misma que GATEWAY_TOKEN en el .env de la laptop
    python gateway_termux.py
    (anota la IP que imprime: esa va en GATEWAY_URL del .env de la laptop)

Mantener la pantalla viva:
    termux-wake-lock
"""

import os
import socket
import subprocess

from flask import Flask, jsonify, request

app = Flask(__name__)

# Clave para que nadie mas en la red del evento mande SMS con tu chip.
# En Termux, ANTES de correr este script:  export GATEWAY_TOKEN="tu-clave"
# Debe ser la MISMA clave que GATEWAY_TOKEN en el .env de la laptop.
TOKEN = os.environ.get("GATEWAY_TOKEN")
if not TOKEN:
    raise SystemExit(
        "Falta GATEWAY_TOKEN. Corre primero: export GATEWAY_TOKEN=\"tu-clave\""
    )

PUERTO = 8080


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/send", methods=["POST"])
def send():
    data = request.get_json(force=True, silent=True) or {}

    if data.get("token") != TOKEN:
        return jsonify({"ok": False, "error": "token invalido"}), 401

    destino = data.get("to")
    cuerpo = data.get("body")
    if not destino or not cuerpo:
        return jsonify({"ok": False, "error": "faltan 'to' o 'body'"}), 400

    try:
        r = subprocess.run(
            ["termux-sms-send", "-n", destino, cuerpo],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return jsonify({"ok": False, "error": r.stderr.strip()}), 500
        print(f"[SMS] -> {destino}: {cuerpo}")
        return jsonify({"ok": True, "to": destino})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "termux-sms-send no respondio"}), 504


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    ip = ip_local()
    print("=" * 46)
    print("  GATEWAY SMS LOCAL - FloodPulse")
    print(f"  Pon esto en el .env de la laptop:")
    print(f"  GATEWAY_URL=http://{ip}:{PUERTO}")
    print("=" * 46)
    app.run(host="0.0.0.0", port=PUERTO)
