"""
Capa de envio de alertas - FloodPulse
Persona 2

Resuelve lo que un solo proveedor no resuelve:

- Abstraccion de proveedor: Vonage, Plivo, Twilio o gateway local detras
  de la misma interfaz. Cambiar de proveedor es una linea del .env.
- Cadena de conmutacion: si el canal primario falla, cae al siguiente.
  PROVEEDORES=vonage,gateway  -> intenta cloud y degrada a gateway local.
- Cola persistente en SQLite: ningun mensaje se pierde si el proceso muere.
- Reintentos con espera creciente y limite de tasa por proveedor.

Lo que esta capa NO resuelve (honestidad para el pitch):
- Confirmacion real de entrega. Requiere webhook publico de callback del
  proveedor; aca solo se registra la aceptacion del mensaje.
- Difusion masiva sin lista de destinatarios. Eso es cell broadcast y
  solo lo puede activar la operadora o el Estado.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone

import requests

DB = os.getenv("COLA_DB", "cola_envios.db")

# Limite de tasa por proveedor (mensajes por minuto). El gateway local es
# el mas restringido: es un SIM personal y las operadoras cortan por spam.
LIMITES = {"vonage": 60, "plivo": 60, "brevo": 60, "twilio": 60, "gateway": 6}

_ultimos = {}


# ----------------------------------------------------------------- proveedores

def _vonage(destino, cuerpo):
    r = requests.post("https://rest.nexmo.com/sms/json", data={
        "api_key": os.getenv("VONAGE_API_KEY"),
        "api_secret": os.getenv("VONAGE_API_SECRET"),
        "from": os.getenv("VONAGE_FROM", "FloodPulse"),
        "to": destino.lstrip("+"),
        "text": cuerpo,
    }, timeout=30)
    r.raise_for_status()
    msg = r.json()["messages"][0]
    if msg["status"] != "0":
        raise RuntimeError(f"vonage {msg['status']}: {msg.get('error-text')}")
    return msg.get("message-id", "ok")


def _plivo(destino, cuerpo):
    auth_id = os.getenv("PLIVO_AUTH_ID")
    r = requests.post(
        f"https://api.plivo.com/v1/Account/{auth_id}/Message/",
        auth=(auth_id, os.getenv("PLIVO_AUTH_TOKEN")),
        json={"src": os.getenv("PLIVO_FROM"), "dst": destino, "text": cuerpo},
        timeout=30,
    )
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"plivo {r.status_code}: {r.text[:120]}")
    return r.json().get("message_uuid", ["ok"])[0]


def _brevo(destino, cuerpo):
    r = requests.post(
        "https://api.brevo.com/v3/transactionalSMS/send",
        headers={"api-key": os.getenv("BREVO_API_KEY"),
                 "content-type": "application/json"},
        json={
            "sender": os.getenv("BREVO_SENDER", "FloodPulse")[:11],  # 11 chars max
            "recipient": destino.lstrip("+"),   # Brevo pide el numero sin '+'
            "content": cuerpo,
            "type": "transactional",
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"brevo {r.status_code}: {r.text[:150]}")
    return str(r.json().get("messageId", "ok"))


def _twilio(destino, cuerpo):
    from twilio.rest import Client
    cli = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    return cli.messages.create(
        body=cuerpo, from_=os.getenv("TWILIO_FROM"), to=destino).sid


def _gateway(destino, cuerpo):
    """Modo degradado: telefono local, sin internet. No escala, no reemplaza
    al agregador; cubre el caso en que el agregador es inalcanzable."""
    r = requests.post(
        f"{os.getenv('GATEWAY_URL')}/send",
        json={"token": os.getenv("GATEWAY_TOKEN"), "to": destino, "body": cuerpo},
        timeout=40,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"gateway: {data.get('error')}")
    return "gateway_ok"


PROVEEDORES = {"vonage": _vonage, "plivo": _plivo, "brevo": _brevo,
               "twilio": _twilio, "gateway": _gateway}


# ------------------------------------------------------------------- cola

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS cola (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creado TEXT, sector TEXT, riesgo REAL, destino TEXT, cuerpo TEXT,
        intentos INTEGER DEFAULT 0, estado TEXT DEFAULT 'pendiente',
        proveedor TEXT, referencia TEXT, ultimo_error TEXT)""")
    con.commit()
    con.close()


def encolar(sector, riesgo, destino, cuerpo):
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO cola (creado,sector,riesgo,destino,cuerpo) VALUES (?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 sector, riesgo, destino, cuerpo))
    con.commit()
    con.close()


def _esperar_tasa(nombre):
    limite = LIMITES.get(nombre, 30)
    intervalo = 60.0 / limite
    ahora = time.time()
    delta = ahora - _ultimos.get(nombre, 0)
    if delta < intervalo:
        time.sleep(intervalo - delta)
    _ultimos[nombre] = time.time()


def _enviar_con_conmutacion(destino, cuerpo, cadena, dry_run):
    """Recorre la cadena de proveedores hasta que uno acepte el mensaje."""
    errores = []
    for nombre in cadena:
        fn = PROVEEDORES.get(nombre)
        if fn is None:
            errores.append(f"{nombre}: proveedor desconocido")
            continue
        if dry_run:
            print(f"    [DRY_RUN/{nombre}] -> {destino}")
            return nombre, "dry_run"
        try:
            _esperar_tasa(nombre)
            ref = fn(destino, cuerpo)
            return nombre, ref
        except Exception as e:
            errores.append(f"{nombre}: {e}")
            print(f"    [FALLO {nombre}] {e} -> degradando")
    raise RuntimeError(" | ".join(errores))


def procesar_cola(cadena=None, max_intentos=4, dry_run=True):
    """Vacia la cola. Los fallos quedan pendientes y se reintentan en el
    siguiente ciclo con espera creciente, no se pierden."""
    cadena = cadena or [p.strip() for p in
                        os.getenv("PROVEEDORES", "gateway").split(",") if p.strip()]
    con = sqlite3.connect(DB)
    filas = con.execute(
        "SELECT id,sector,riesgo,destino,cuerpo,intentos FROM cola "
        "WHERE estado='pendiente' AND intentos < ? ORDER BY id", (max_intentos,)
    ).fetchall()

    for _id, sector, riesgo, destino, cuerpo, intentos in filas:
        if intentos:
            espera = min(2 ** intentos * 5, 120)   # 10s, 20s, 40s...
            print(f"  reintento {intentos+1} de {destino} en {espera}s")
            time.sleep(espera)
        try:
            proveedor, ref = _enviar_con_conmutacion(destino, cuerpo, cadena, dry_run)
            con.execute("UPDATE cola SET estado='enviado',intentos=intentos+1,"
                        "proveedor=?,referencia=? WHERE id=?", (proveedor, ref, _id))
            print(f"  [OK/{proveedor}] {destino} ({ref})")
        except Exception as e:
            nuevo = intentos + 1
            estado = "fallido" if nuevo >= max_intentos else "pendiente"
            con.execute("UPDATE cola SET intentos=?,estado=?,ultimo_error=? WHERE id=?",
                        (nuevo, estado, str(e)[:300], _id))
            print(f"  [{estado.upper()}] {destino}: {e}")
        con.commit()
    con.close()


def resumen():
    con = sqlite3.connect(DB)
    filas = con.execute("SELECT estado,COUNT(*) FROM cola GROUP BY estado").fetchall()
    con.close()
    return dict(filas)
