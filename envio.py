"""
Capa de envio de alertas - FloodPulse
Persona 2

Resuelve lo que un solo proveedor no resuelve:

- Abstraccion de proveedor: AWS SNS, Twilio o gateway local detras de la
  misma interfaz. Cambiar de proveedor es una linea del .env.
- Cadena de conmutacion: si el canal primario falla, cae al siguiente.
  PROVEEDORES=aws,gateway  -> intenta cloud y degrada a gateway local.
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
LIMITES = {"twilio": 60, "aws": 60, "gateway": 6}

_ultimos = {}


# ----------------------------------------------------------------- proveedores

def _aws_sns(destino, cuerpo):
    import boto3
    cliente = boto3.client(
        "sns",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )
    resp = cliente.publish(
        PhoneNumber=destino,   # formato E.164 completo, con el '+'
        Message=cuerpo,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
            "AWS.SNS.SMS.SenderID": {"DataType": "String",
                                     "StringValue": os.getenv("AWS_SENDER_ID", "FLOODPULSE")},
        },
    )
    return resp["MessageId"]


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


PROVEEDORES = {"twilio": _twilio, "aws": _aws_sns, "gateway": _gateway}


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