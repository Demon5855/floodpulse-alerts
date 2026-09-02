# FloodPulse — Motor de Alertas SMS

Componente de entrega de alertas del sistema FloodPulse
(HackTech El Niño 2026 — Track 1: Telecomunicaciones y Sistemas de Alerta
Temprana en Crisis).

Consulta el índice de riesgo hiperlocal que expone el
[backend](https://github.com/1Said2/floodpulse-backend) y, cuando un sector
cruza su umbral, envía un SMS a las personas registradas en ese sector.

---

## Arquitectura

El sistema separa **la decisión** de **la entrega**. Esa separación es
deliberada: el motor de riesgo puede vivir en cualquier parte (un servidor
municipal, la nube), mientras que el canal de entrega es intercambiable y
puede degradarse a infraestructura local cuando la conectividad falla.

    ┌──────────────────┐   GET /risk    ┌─────────────────┐
    │  Backend riesgo  │ ←───────────── │   alerta_sms    │
    │                  │                │   (monitor)     │
    └──────────────────┘                └────────┬────────┘
                                                 │ encola
    ┌──────────────────┐   POST         ┌────────▼────────┐
    │    Dashboard     │ ─────────────► │ api_suscriptores│
    │                  │  /suscriptores │   (FastAPI)     │
    └──────────────────┘                └────────┬────────┘
                                                 │ a quién avisar
                                        ┌────────▼────────┐
                                        │      envio      │
                                        │  cola + reintent│
                                        └────┬───────┬────┘
                                   cloud     │       │    local
                              ┌──────────────▼─┐ ┌───▼──────────────┐
                              │ Vonage / Plivo │ │ Gateway Android  │
                              │    / Twilio    │ │   (Termux)       │
                              └────────────────┘ └──────────────────┘

## Por qué SMS

Durante una inundación, la red de datos es lo primero que falla. El SMS viaja
sobre la red 2G de voz, que se mantiene en pie cuando el 4G ya cayó, y llega a
cualquier teléfono sin instalar nada.

**Canal primario (cloud).** Un agregador de SMS entrega a escala: miles de
destinatarios, sin límites de SIM, con la infraestructura del operador.

**Canal degradado (gateway local).** Un teléfono Android con Termux envía por
su propio chip. No reemplaza al agregador ni pretende escalar: cubre el
escenario en que el agregador es inalcanzable porque cayó la conectividad de
la zona. Una junta parroquial puede operarlo sin contrato ni internet.

La cadena se configura en `PROVEEDORES` y se recorre en orden hasta que un
canal acepte el mensaje:

    PROVEEDORES=vonage,gateway    # cloud primario, degrada a local
    PROVEEDORES=gateway           # solo local (demo sin internet)

### Límites conocidos

Se documentan explícitamente porque condicionan cualquier despliegue real:

- **Sin confirmación de entrega.** Se registra la aceptación del mensaje por
  el proveedor, no su recepción. La confirmación real requiere exponer un
  webhook público que reciba los callbacks del proveedor.
- **El gateway local no escala.** Un SIM personal tiene límites de envío por
  hora y las operadoras lo bloquean ante patrones de spam. Por eso su límite
  de tasa está fijado en 6 mensajes/minuto frente a 60 del canal cloud.
- **Un solo nodo gateway es punto único de falla.** La redundancia real
  implicaría varios nodos, uno por parroquia, con cola propia.
- **Alcance regulatorio.** Un sistema nacional de alerta se difunde por *cell
  broadcast*, que solo puede activar la operadora o el Estado. Este componente
  demuestra el mecanismo; el canal definitivo corresponde a la institución
  que tenga la potestad legal.

---

## Componentes

| Archivo | Qué es |
|---|---|
| `run.py` | Lanzador con menú. Punto de entrada recomendado. |
| `alerta_sms.py` | Monitor: consulta el riesgo por sector y decide cuándo alertar. |
| `envio.py` | Módulo (no se ejecuta): proveedores, cola, reintentos, límite de tasa. |
| `api_suscriptores.py` | API FastAPI de alta y baja de destinatarios. |
| `gateway_termux.py` | Gateway SMS que corre en el teléfono Android. |
| `mock_risk_api.py` | API de riesgo simulada, para probar sin el backend. |
| `suscriptores.json` | Sectores monitoreados: coordenadas y umbrales. |

## Lógica de alerta

Un sector alerta cuando su `risk_score` cruza el umbral, con dos protecciones
contra el exceso de mensajes:

- **Histéresis** — una vez disparada la alerta, el sector debe bajar del umbral
  de salida antes de poder volver a alertar. Evita el rebote cuando el score
  oscila alrededor del umbral.
- **Cooldown** — mínimo de minutos entre alertas del mismo sector.

El umbral es **por sector**, no global: la parte estática de la fórmula de
riesgo (pendiente del terreno, cercanía al cauce, impermeabilización) aporta
una base distinta en cada lugar, y la lluvia satura a los 25 mm. Un umbral
fijo dejaría sectores que nunca alertan. El modo `calibrar` barre valores de
lluvia de 0 a 25 mm contra la API real para determinar el umbral de cada uno.

Los envíos pasan por una cola persistente en SQLite: si el proceso muere, los
mensajes pendientes sobreviven y se reintentan con espera creciente.

---

## Instalación

    pip install -r requirements.txt
    copiar .env.example a .env y completarlo

## Uso

    python run.py

    1. Monitor de alertas
    2. Calibrar umbrales por sector
    3. API de suscriptores (Swagger en /docs)
    4. Mock de la API de riesgo
    5. Levantar todo
    6. Diagnóstico — estado de servicios, cola y suscriptores

`DRY_RUN = True` (por defecto en `alerta_sms.py`) imprime las alertas sin
enviarlas. `RAINFALL_MM` fija un valor de lluvia para pruebas; en `None` el
backend usa el dato satelital real. El monitor avisa al arrancar en qué modo
está.

---

## API de suscriptores

Swagger interactivo en `http://localhost:8100/docs`.
Autenticación por cabecera `X-API-Key` (botón *Authorize* en Swagger).

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del servicio. Sin autenticación. |
| `GET` | `/sectores` | Sectores válidos, para poblar el formulario. |
| `GET` | `/suscriptores` | Registrados. Teléfonos enmascarados. |
| `POST` | `/suscriptores` | Alta. Requiere consentimiento del titular. |
| `DELETE` | `/suscriptores` | Baja voluntaria. |

Ejemplo de alta:

    POST /suscriptores
    X-API-Key: <clave>
    {"telefono": "+593987654321", "sector": "Malacatos, Loja",
     "consentimiento": true}

Los teléfonos son datos personales: se registran solo con consentimiento
explícito, se devuelven enmascarados en las consultas y la baja está
disponible en todo momento.

---

## Gateway en el teléfono

Instalar desde **F-Droid** (no Play Store: esa versión no puede enviar SMS)
las apps **Termux** y **Termux:API**. Luego, en Termux:

    pkg update && pkg install python termux-api
    pip install flask
    termux-sms-send -n +593XXXXXXXXX "prueba"   # aceptar el permiso de SMS
    export GATEWAY_TOKEN="<la misma clave del .env>"
    python gateway_termux.py

El script imprime al arrancar la IP que debe ir en `GATEWAY_URL`.

Antes de una demostración:

    termux-wake-lock    # en otra sesión: evita que Android duerma el proceso

La IP cambia con cada red. Si no hay red disponible, levantar el hotspot del
teléfono y conectar el equipo a él — el sistema queda operando sin internet.

Verificación rápida (PowerShell):

    Invoke-RestMethod http://IP:8080/health
