"""
API de suscriptores - FloodPulse

Endpoint para que el dashboard registre a las personas que reciben alertas
en cada sector. Los sectores (coordenadas, umbrales) siguen viviendo en
suscriptores.json; aqui solo se administran los telefonos.

    pip install fastapi uvicorn
    uvicorn api_suscriptores:app --host 0.0.0.0 --port 8100 --reload

    Swagger:  http://localhost:8100/docs

Autenticacion: cabecera  X-API-Key: <API_KEY del .env>
En Swagger, boton "Authorize" arriba a la derecha.

Nota: los telefonos son datos personales. Se guardan solo con consentimiento
del titular y se pueden dar de baja en cualquier momento (DELETE).
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator

load_dotenv()

DB = os.getenv("SUSCRIPTORES_DB", "suscriptores.db")
API_KEY = os.getenv("API_KEY", "cambiame")
SECTORES_JSON = "suscriptores.json"

# Ecuador: +593 seguido de 9 digitos
TELEFONO_RE = re.compile(r"^\+593[0-9]{9}$")

app = FastAPI(
    title="FloodPulse — API de Suscriptores",
    description="Alta y baja de personas que reciben alertas SMS por sector.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGEN", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verificar_clave(clave: str = Depends(api_key_header)):
    if clave != API_KEY:
        raise HTTPException(status_code=401, detail="API key invalida o ausente")
    return clave


# ------------------------------------------------------------------ modelos

class SuscriptorIn(BaseModel):
    telefono: str
    sector: str
    consentimiento: bool = True

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v):
        limpio = v.replace(" ", "").replace("-", "")
        if not TELEFONO_RE.match(limpio):
            raise ValueError("formato esperado +593XXXXXXXXX")
        return limpio

    model_config = {"json_schema_extra": {"examples": [
        {"telefono": "+593987654321", "sector": "Malacatos, Loja",
         "consentimiento": True}]}}


class SuscriptorOut(BaseModel):
    telefono: str
    sector: str
    alta: str

class TestAlertIn(BaseModel):
    sector: str
    riesgo: float


# --------------------------------------------------------------------- datos

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS suscriptores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telefono TEXT NOT NULL,
        sector TEXT NOT NULL,
        alta TEXT NOT NULL,
        activo INTEGER DEFAULT 1,
        UNIQUE(telefono, sector))""")
    con.commit()
    con.close()


def sectores_validos():
    with open(SECTORES_JSON, encoding="utf-8") as f:
        return [s["sector"] for s in json.load(f)]


def enmascarar(tel):
    return tel[:6] + "*" * (len(tel) - 9) + tel[-3:]


def telefonos_de(sector: str):
    """La usa alerta_sms.py para saber a quien avisar."""
    init_db()
    con = sqlite3.connect(DB)
    filas = con.execute("SELECT telefono FROM suscriptores WHERE activo=1 AND sector=?",
                        (sector,)).fetchall()
    con.close()
    return [f[0] for f in filas]


# ----------------------------------------------------------------- endpoints

@app.get("/health", tags=["estado"])
def health():
    """Sin autenticacion: sirve para comprobar que el servicio esta arriba."""
    return {"ok": True, "servicio": "suscriptores"}


@app.get("/sectores", tags=["sectores"], dependencies=[Depends(verificar_clave)])
def get_sectores():
    """Sectores disponibles. Usar para llenar el desplegable del formulario."""
    return {"ok": True, "sectores": sectores_validos()}


@app.get("/suscriptores", tags=["suscriptores"], dependencies=[Depends(verificar_clave)])
def listar(sector: str | None = Query(None, description="Filtrar por sector")):
    """Lista de registrados. Los telefonos salen enmascarados."""
    con = sqlite3.connect(DB)
    sql = "SELECT telefono,sector,alta FROM suscriptores WHERE activo=1"
    filas = (con.execute(sql + " AND sector=?", (sector,)).fetchall() if sector
             else con.execute(sql).fetchall())
    con.close()
    return {"ok": True, "total": len(filas),
            "suscriptores": [SuscriptorOut(telefono=enmascarar(t), sector=s, alta=a)
                             for t, s, a in filas]}


@app.post("/suscriptores", tags=["suscriptores"], status_code=201,
          dependencies=[Depends(verificar_clave)])
def registrar(sus: SuscriptorIn):
    """Da de alta un telefono en un sector. Requiere consentimiento del titular."""
    if not sus.consentimiento:
        raise HTTPException(400, "se requiere consentimiento del titular")

    validos = sectores_validos()
    if sus.sector not in validos:
        raise HTTPException(400, f"sector desconocido. Validos: {validos}")

    init_db()
    con = sqlite3.connect(DB)
    con.execute("""INSERT INTO suscriptores (telefono,sector,alta,activo)
                   VALUES (?,?,?,1)
                   ON CONFLICT(telefono,sector) DO UPDATE SET activo=1""",
                (sus.telefono, sus.sector,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    con.close()
    print(f"[ALTA] {enmascarar(sus.telefono)} -> {sus.sector}")
    return {"ok": True, "telefono": enmascarar(sus.telefono), "sector": sus.sector}


@app.delete("/suscriptores", tags=["suscriptores"], dependencies=[Depends(verificar_clave)])
def baja(telefono: str = Query(..., description="+593XXXXXXXXX"),
         sector: str = Query(...)):
    """Baja voluntaria. No borra el registro, lo marca inactivo."""
    init_db()
    con = sqlite3.connect(DB)
    cur = con.execute("UPDATE suscriptores SET activo=0 WHERE telefono=? AND sector=?",
                      (telefono.replace(" ", ""), sector))
    con.commit()
    afectados = cur.rowcount
    con.close()
    if not afectados:
        raise HTTPException(404, "no estaba registrado")
    return {"ok": True, "baja": enmascarar(telefono), "sector": sector}


@app.post("/test_alert", tags=["suscriptores"], dependencies=[Depends(verificar_clave)])
def test_alert(alert: TestAlertIn):
    """Encola y dispara un SMS de prueba para el sector, llamado desde el frontend."""
    import envio
    telefonos = telefonos_de(alert.sector)
    if not telefonos:
        raise HTTPException(404, "No hay suscriptores en este sector para alertar.")
    
    for t in telefonos:
        cuerpo = f"🚨 SIMULACION FLOODPULSE: Riesgo critico ({alert.riesgo:.1f}) en {alert.sector}. SMS de prueba desde el Dashboard."
        envio.encolar(alert.sector, alert.riesgo, t, cuerpo)
        
    try:
        # Procesamos la cola de envio inmediatamente, usando los proveedores del .env (o gateway)
        envio.procesar_cola(dry_run=False)
    except Exception as e:
        print(f"Error procesando cola desde test_alert: {e}")
        
    return {"ok": True, "enviados": len(telefonos)}


init_db()
