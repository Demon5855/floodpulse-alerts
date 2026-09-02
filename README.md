# FloodPulse — Motor de Alertas SMS

Componente de entrega de alertas del sistema FloodPulse
(HackTech El Niño 2026 — Track 1: Telecomunicaciones y Sistemas de
Alerta Temprana en Crisis).

Consulta el índice de riesgo hiperlocal que expone el
[backend](https://github.com/1Said2/floodpulse-backend) y, cuando un
sector cruza su umbral, envía un SMS a las personas registradas en ese
sector.

## Por qué SMS y no una app

Durante una inundación, la infraestructura de datos es lo primero que
falla. El SMS viaja sobre la red 2G de voz, que se mantiene en pie
cuando el 4G ya cayó, y llega a cualquier teléfono sin necesidad de
instalar nada.

El sistema soporta dos vías de envío, seleccionables con la variable
`PROVEEDOR`:

- **`gateway`** — un teléfono Android local actúa como gateway y envía
  por su propio chip. No depende de ningún proveedor externo ni de
  internet: basta con que el servidor y el teléfono estén en la misma
  red (o en el hotspot del propio teléfono). Es el modo pensado para
  operación en territorio.
- **`twilio`** — envío por proveedor cloud. Mayor alcance, pero depende
  de conectividad a internet y de un servicio de terceros.

## Estructura

    alerta_sms.py       servicio principal: consulta riesgo y dispara alertas
    gateway_termux.py   gateway SMS que corre en el teléfono Android
    mock_risk_api.py    API de riesgo simulada, para probar sin el backend
    suscriptores.json   sectores monitoreados, umbrales y destinatarios

## Lógica de alerta

Un sector alerta cuando su `risk_score` cruza el umbral, con dos
protecciones contra el exceso de mensajes:

- **Histéresis** — una vez disparada la alerta, el sector debe bajar del
  umbral de salida antes de poder volver a alertar. Evita el rebote
  cuando el score oscila alrededor del umbral.
- **Cooldown** — mínimo de minutos entre alertas del mismo sector.

El umbral es **por sector**, no global: la parte estática de la fórmula
de riesgo (pendiente del terreno, cercanía al cauce, impermeabilización)
ya aporta una base distinta en cada lugar. El modo `calibrar` barre
valores de lluvia de 0 a 25mm para determinar el umbral adecuado de cada
sector.

Cada envío queda registrado en `envios.csv` con sector, riesgo, destino
y resultado.

## Instalación

    pip install requests python-dotenv twilio flask
    copiar .env.example a .env y completarlo

## Uso

    python alerta_sms.py            # monitoreo continuo
    python alerta_sms.py calibrar   # barrido de lluvia por sector

`DRY_RUN = True` (por defecto) imprime las alertas sin enviarlas.

## Gateway en el teléfono

Instalar desde **F-Droid** (no Play Store: esa versión no puede enviar
SMS) las apps **Termux** y **Termux:API**. Luego, en Termux:

    pkg update && pkg install python termux-api
    pip install flask
    termux-sms-send -n +593XXXXXXXXX "prueba"   # aceptar el permiso de SMS
    python gateway_termux.py

El script imprime al arrancar la IP que debe ir en `GATEWAY_URL`.

Antes de una demostración:

    termux-wake-lock    # en otra sesión, evita que Android duerma el proceso

La IP cambia con cada red. Si no hay red disponible, levantar el hotspot
del teléfono y conectar el servidor a él.

Verificación rápida (PowerShell):

    Invoke-RestMethod http://IP:8080/health
