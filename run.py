"""
Lanzador - FloodPulse Alertas

Menu para levantar los servicios sin recordar comandos.

    python run.py

Nota: envio.py NO se ejecuta, es un modulo que usa alerta_sms.py.
"""

import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

PY = sys.executable
ES_WINDOWS = os.name == "nt"


def lanzar(cmd, titulo, nueva_ventana=False):
    """Ejecuta un comando. Si nueva_ventana, lo abre aparte y no bloquea."""
    print(f"\n>>> {titulo}\n    {' '.join(cmd)}\n")
    if nueva_ventana and ES_WINDOWS:
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        print("    Abierto en una ventana nueva.")
        return
    if nueva_ventana:
        subprocess.Popen(cmd)
        print("    Corriendo en segundo plano.")
        return
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n    Detenido.")


def monitor(nueva=False):
    lanzar([PY, "alerta_sms.py"], "Monitor de alertas", nueva)


def calibrar():
    print("\nOJO: cada llamada al backend real puede tardar minutos.")
    lanzar([PY, "alerta_sms.py", "calibrar"], "Calibracion de umbrales")


def api_suscriptores(nueva=False):
    puerto = os.getenv("PUERTO_SUSCRIPTORES", "8100")
    print(f"\n    Swagger: http://localhost:{puerto}/docs")
    lanzar([PY, "-m", "uvicorn", "api_suscriptores:app",
            "--host", "0.0.0.0", "--port", puerto], "API de suscriptores", nueva)


def mock():
    lanzar([PY, "mock_risk_api.py"], "Mock de la API de riesgo (puerto 8000)")


def todo():
    """Los dos servicios que conviven en operacion normal."""
    api_suscriptores(nueva=True)
    monitor(nueva=True)
    print("\n    Los dos servicios quedaron corriendo en ventanas aparte.")


def diagnostico():
    import requests

    print("\n--- Configuracion ---")
    for var in ("API_BASE", "GATEWAY_URL", "PROVEEDORES", "PUERTO_SUSCRIPTORES"):
        print(f"  {var:22} {os.getenv(var) or '(sin definir)'}")
    for var in ("GATEWAY_TOKEN", "API_KEY"):
        print(f"  {var:22} {'definido' if os.getenv(var) else 'SIN DEFINIR'}")

    print("\n--- Servicios ---")
    destinos = [
        ("Gateway SMS", f"{os.getenv('GATEWAY_URL', '')}/health"),
        ("API de riesgo", f"{os.getenv('API_BASE', '')}/docs"),
        ("API suscriptores",
         f"http://localhost:{os.getenv('PUERTO_SUSCRIPTORES', '8100')}/health"),
    ]
    for nombre, url in destinos:
        if not url.startswith("http"):
            print(f"  {nombre:20} sin URL configurada")
            continue
        try:
            r = requests.get(url, timeout=8)
            print(f"  {nombre:20} OK ({r.status_code})")
        except Exception as e:
            print(f"  {nombre:20} sin respuesta -> {type(e).__name__}")

    print("\n--- Cola de envios ---")
    try:
        import envio
        envio.init_db()
        print(f"  {envio.resumen() or 'vacia'}")
    except Exception as e:
        print(f"  no se pudo leer: {e}")

    print("\n--- Sectores ---")
    try:
        import json
        from api_suscriptores import telefonos_de
        for s in json.load(open("suscriptores.json", encoding="utf-8")):
            n = len(telefonos_de(s["sector"]))
            print(f"  {s['sector']:22} umbral {s.get('umbral')}  |  {n} suscriptores")
    except Exception as e:
        print(f"  no se pudo leer: {e}")


OPCIONES = {
    "1": ("Monitor de alertas", monitor),
    "2": ("Calibrar umbrales por sector", calibrar),
    "3": ("API de suscriptores (Swagger)", api_suscriptores),
    "4": ("Mock de la API de riesgo", mock),
    "5": ("Levantar todo (monitor + API)", todo),
    "6": ("Diagnostico", diagnostico),
}


def menu():
    while True:
        print("\n" + "=" * 42)
        print("  FloodPulse - Alertas SMS")
        print("=" * 42)
        for k, (texto, _) in OPCIONES.items():
            print(f"  {k}. {texto}")
        print("  0. Salir")

        eleccion = input("\n  Opcion: ").strip()
        if eleccion in ("0", "q", ""):
            print("  Listo.")
            return
        entrada = OPCIONES.get(eleccion)
        if not entrada:
            print("  Opcion no valida.")
            continue
        try:
            entrada[1]()
        except KeyboardInterrupt:
            print("\n  Detenido.")
        except Exception as e:
            print(f"\n  Error: {e}")


if __name__ == "__main__":
    if not os.path.exists(".env"):
        print("AVISO: no hay archivo .env. Copia .env.example a .env y completalo.\n")
    menu()
