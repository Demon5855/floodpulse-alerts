"""
Servicio de alertas SMS - FloodPulse

Consume la API de riesgo (FloodPulse backend) y dispara SMS por Twilio
cuando un sector cruza su umbral.

    pip install twilio python-dotenv requests

Modos:
    python alerta_sms.py            -> monitoreo continuo
    python alerta_sms.py calibrar   -> barre lluvia 0..25mm por sector
                                       para descubrir el umbral de cada uno

"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

import envio
from api_suscriptores import telefonos_de

load_dotenv()

# ---------------------------------------------------------------
# DRY_RUN=True no envia nada, solo imprime. Los SMS gratis son
# limitados: ponlo en False solo cuando pruebes de verdad.
# ---------------------------------------------------------------
DRY_RUN = True

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
TIMEOUT_S = 180           # el endpoint corre Whitebox/TWI por llamada: es LENTO
POLL_SEGUNDOS = 900       # 15 min. Bajalo a 60 solo para probar.

# rainfall_mm de prueba. OJO: la formula satura en 25mm
# (config.py -> max_rainfall_mm), pasar 40 o 90 da el MISMO score.
RAINFALL_MM = 20          # None = que la API traiga la lluvia real (requiere Earth Engine)

COOLDOWN_MIN = 30
BITACORA = "envios.csv"

# Proveedor de envio: "gateway" (celular con Termux) o "twilio"
PROVEEDOR = "brevo"

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://192.168.1.50:8080")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN")   # sin default: va solo en el .env

_twilio = None
NUMERO_ORIGEN = os.getenv("TWILIO_FROM")


def twilio_client():
    """Se crea solo si de verdad se usa Twilio (asi no estorba si no hay credenciales)."""
    global _twilio
    if _twilio is None:
        from twilio.rest import Client
        _twilio = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    return _twilio

estado = {}   # {sector: {"ultimo_envio": datetime, "en_alerta": bool}}


def cargar_suscriptores(ruta="suscriptores.json"):
    """Sectores desde el JSON (configuracion) + telefonos desde la base que
    administra la API de suscriptores. Se relee en cada ciclo, asi las altas
    que haga el dashboard entran sin reiniciar el servicio."""
    with open(ruta, encoding="utf-8") as f:
        sectores = json.load(f)
    for s in sectores:
        registrados = telefonos_de(s["sector"])
        if registrados:
            s["telefonos"] = registrados
        else:
            s.setdefault("telefonos", [])
    return sectores


def consultar_riesgo(s, rainfall_mm=RAINFALL_MM):
    """GET /risk -> (risk_score, components). Devuelve el MAXIMO de la grilla."""
    params = {"lat": s["lat"], "lon": s["lon"]}
    if rainfall_mm is not None:
        params["rainfall_mm"] = rainfall_mm
    if s.get("bbox_offset_deg"):
        params["bbox_offset_deg"] = s["bbox_offset_deg"]
    # Necesario donde el cauce esta embovedado y no aparece en OSM (caso Ajavi)
    if s.get("fallback_waterway_coords"):
        params["fallback_waterway_coords"] = json.dumps(s["fallback_waterway_coords"])

    r = requests.get(f"{API_BASE}/risk", params=params, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    return float(data["risk_score"]), data.get("components", {})


def construir_mensaje(sector, riesgo, hora):
    """160 caracteres, sin tildes ni emojis, con una accion concreta."""
    return (
        f"ALERTA INUNDACION - {sector}. "
        f"Riesgo ALTO ({int(riesgo)}/100). {hora}. "
        f"Aleje vehiculos y suba pertenencias. No cruce quebradas."
    )


def registrar(sector, riesgo, destino, resultado):
    nuevo = not os.path.exists(BITACORA)
    with open(BITACORA, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["timestamp", "sector", "riesgo", "destino", "resultado"])
        w.writerow([datetime.now().isoformat(timespec="seconds"),
                    sector, riesgo, destino, resultado])


def enviar_por_gateway(destino, cuerpo):
    """Manda el SMS por el chip del celular (Termux). Sin internet: solo LAN/hotspot."""
    r = requests.post(
        f"{GATEWAY_URL}/send",
        json={"token": GATEWAY_TOKEN, "to": destino, "body": cuerpo},
        timeout=40,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", f"HTTP {r.status_code}"))
    return "gateway_ok"


def enviar_por_twilio(destino, cuerpo):
    msg = twilio_client().messages.create(body=cuerpo, from_=NUMERO_ORIGEN, to=destino)
    return msg.sid


def enviar_sms(destino, cuerpo):
    if DRY_RUN:
        print(f"  [DRY_RUN/{PROVEEDOR}] -> {destino}: {cuerpo}")
        return "dry_run"

    if PROVEEDOR == "gateway":
        res = enviar_por_gateway(destino, cuerpo)
    else:
        res = enviar_por_twilio(destino, cuerpo)
    print(f"  [ENVIADO/{PROVEEDOR}] {res} -> {destino}")
    return res


def debe_alertar(sector, riesgo, umbral, salida):
    st = estado.setdefault(sector, {"ultimo_envio": None, "en_alerta": False})

    if riesgo < salida:
        st["en_alerta"] = False        # el sector se normalizo, se rearma
        return False
    if riesgo < umbral:
        return False
    if st["en_alerta"]:
        ultimo = st["ultimo_envio"]
        if ultimo and datetime.now() - ultimo < timedelta(minutes=COOLDOWN_MIN):
            return False
    return True


def procesar(s, riesgo):
    sector = s["sector"]
    # Umbral POR SECTOR: la parte estatica de la formula (TWI + cercania al
    # cauce + impermeabilizacion) ya aporta hasta 60 pts sin llover nada,
    # asi que un 70 fijo no sirve para todos. Calibrar con el modo 'calibrar'.
    umbral = s.get("umbral", 70)
    salida = s.get("umbral_salida", umbral - 10)

    if not debe_alertar(sector, riesgo, umbral, salida):
        print(f"  sin alerta (riesgo {riesgo} / umbral {umbral})")
        return

    hora = datetime.now().strftime("%H:%M")
    cuerpo = construir_mensaje(sector, riesgo, hora)
    print(f"  ALERTA! {len(cuerpo)} caracteres")

    # Se encola: la entrega la maneja envio.py con conmutacion de proveedor,
    # reintentos y limite de tasa. Si el proceso muere, la cola sobrevive.
    for destino in s["telefonos"]:
        envio.encolar(sector, riesgo, destino, cuerpo)
        registrar(sector, riesgo, destino, "encolado")
    envio.procesar_cola(dry_run=DRY_RUN)

    estado[sector]["ultimo_envio"] = datetime.now()
    estado[sector]["en_alerta"] = True


def modo_calibrar(suscriptores):
    """Barre lluvia de 0 a 25mm (arriba de 25 la formula se satura)
    para ver donde cruza el score de cada sector y fijar su umbral."""
    for s in suscriptores:
        print(f"\n=== {s['sector']} ===")
        for mm in [0, 5, 10, 15, 20, 25]:
            t0 = time.time()
            try:
                riesgo, comp = consultar_riesgo(s, rainfall_mm=mm)
                print(f"  lluvia {mm:>2}mm -> riesgo {riesgo:6.2f}  "
                      f"(twi {comp.get('twi_max')}, dist {comp.get('distance_to_channel_m')}m, "
                      f"imperv {comp.get('imperviousness_pct')}%)  [{time.time()-t0:.0f}s]")
            except Exception as e:
                print(f"  lluvia {mm:>2}mm -> ERROR: {e}")


def ciclo(suscriptores):
    for s in suscriptores:
        print(f"[{datetime.now():%H:%M:%S}] {s['sector']}")
        try:
            riesgo, _ = consultar_riesgo(s)
        except Exception as e:
            print(f"  [ERROR] API: {e}")
            continue
        procesar(s, riesgo)


if __name__ == "__main__":
    suscriptores = cargar_suscriptores()

    if len(sys.argv) > 1 and sys.argv[1] == "calibrar":
        modo_calibrar(suscriptores)
        sys.exit(0)

    envio.init_db()

    if PROVEEDOR == "gateway" and not DRY_RUN:
        try:
            requests.get(f"{GATEWAY_URL}/health", timeout=5).raise_for_status()
            print(f"Gateway vivo en {GATEWAY_URL}")
        except Exception as e:
            print(f"[AVISO] no alcanzo el gateway ({e}). Esta el celular en la misma red?")

    if RAINFALL_MM is None:
        print(">>> MODO REAL: la lluvia viene de GPM IMERG + Open-Meteo\n")
    else:
        print(f">>> MODO SIMULADO: lluvia fijada en {RAINFALL_MM}mm. "
              f"Para la demo real poner RAINFALL_MM = None\n")

    print(f"Monitoreando {len(suscriptores)} sectores | DRY_RUN={DRY_RUN} | via {PROVEEDOR} "
          f"| rainfall_mm={RAINFALL_MM} | cada {POLL_SEGUNDOS}s\n")
    while True:
        suscriptores = cargar_suscriptores()   # recarga altas nuevas
        ciclo(suscriptores)
        envio.procesar_cola(dry_run=DRY_RUN)   # reintenta lo que quedo pendiente
        print(f"  cola: {envio.resumen()}")
        time.sleep(POLL_SEGUNDOS)