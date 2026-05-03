> [🇺🇸 English](README.md) · 🇲🇽 Español

# TelemetryStack — Sistema de Telemetría SAE

Desarrollado por **Luis Xavier García Pimentel Ascencio**.
Stack de telemetría en tiempo real para vehículos SAE (Minibaja, Formula, Baja). Diseñado para ser adoptado por cualquier equipo con configuración mínima.

**Stack local (sin internet):**
```
ESP32 LoRa TX ──915MHz──► ESP32 LoRa RX ──USB──► lora_receiver_local.py ──► InfluxDB (Docker) ──► Grafana
    (coche)                   (pits)                   localDashboard/laptop/
```

**Stack live (con internet):**
```
ESP32 ──WiFi──► Hotspot (celular) ──Internet──► InfluxDB Cloud ──► Grafana Cloud
(coche)              liveDashboard/firmware/
```

**Dashboard HTML** *(en desarrollo)* — standalone sin Docker, via WebSocket MQTT.

---

## Estructura del repositorio

```
TelemetryStack/
├── README.md
├── README.es.md
├── LICENSE
├── .gitignore
├── .gitattributes
├── localDashboard/
│   ├── firmware/                   ← ESP32: TX (coche) + RX (pits) via LoRa
│   │   ├── README.md
│   │   ├── arduino/                ← completo, listo para flashear
│   │   │   ├── transmitter/
│   │   │   │   ├── transmitter.ino
│   │   │   │   ├── config.h.example
│   │   │   │   └── config.h        ← gitignored, llenar con valores reales
│   │   │   └── receiver/
│   │   │       ├── receiver.ino
│   │   │       ├── config.h.example
│   │   │       └── config.h
│   │   └── cpp/                    ← esqueleto ESP-IDF (estructura + TODOs)
│   │       ├── transmitter/
│   │       └── receiver/
│   ├── laptop/                     ← código a correr en la laptop de pits
│   │   ├── lora_receiver_local.py  ← serial → InfluxDB local
│   │   ├── sd_upload.py            ← sube CSV de SD card → InfluxDB
│   │   └── dataSimulator/
│   │       └── lora_serial_sim.py  ← simula ESP32 por serial virtual
│   ├── docker-compose.yml
│   ├── .env                        ← credenciales reales (NO commitear)
│   ├── .env.example                ← plantilla para nuevos miembros
│   └── grafana/
│       └── provisioning/
│           └── datasources/
│               └── influxdb.yml
├── liveDashboard/
│   ├── firmware/                   ← ESP32: TX directo a InfluxDB Cloud via WiFi
│   │   ├── README.md
│   │   └── transmitter/
│   │       ├── transmitter.ino     ← completo, listo para flashear
│   │       ├── config.h.example
│   │       └── config.h            ← gitignored, llenar con credenciales reales
│   ├── dataSimulator/
│   │   └── simulator.py            ← simula vehículo → InfluxDB Cloud
│   ├── .env                        ← credenciales reales (NO commitear)
│   └── .env.example
└── htmlDashboard/                  ← en desarrollo
    └── README.md
```

---

## Adaptar al equipo

Solo hay que editar el archivo `.env` — nada más en el código cambia entre equipos.

```bash
cd localDashboard
cp .env.example .env
```

Variables a personalizar en `.env`:

| Variable | Descripción | Ejemplo | Stack |
|---|---|---|---|
| `INFLUX_TOKEN` | Token de InfluxDB | `mi-token-secreto` | ambos |
| `INFLUX_PASSWORD` | Password admin de InfluxDB | `mi-password` | local |
| `GF_PASSWORD` | Password de Grafana | `mi-password` | local |
| `INFLUX_ORG` | Nombre de la organización en InfluxDB | `mi-equipo` | ambos |
| `INFLUX_BUCKET` | Bucket de datos | `Telemetry` | ambos |
| `INFLUX_MEASUREMENT` | Nombre del measurement que escriben los scripts de Python. Debe coincidir con el nombre que selecciones en el filtro **Measurement** de Grafana. Cada proyecto usa el suyo (ej. Minibaja SAE → `minibaja`, Formula SAE → `formula`). | `minibaja` | ambos |
| `TEAM_NAME` | Tag del equipo en cada punto de datos | `mi-equipo` | ambos |
| `TRACK_LAT` | Latitud central de la pista (simulador) | `43.734722` | live |
| `TRACK_LNG` | Longitud central de la pista (simulador) | `7.420556` | live |

Los datos GPS en producción vienen directamente del sensor GPS del vehículo.

---

## Requisitos generales

- Python 3.10+
- Docker Desktop (solo para stack local)

```bash
pip install pyserial influxdb-client paho-mqtt python-dotenv requests
```

---

## Stack Local — sin internet

InfluxDB + Grafana corren en Docker en la laptop de pits. Dos buckets se crean automáticamente:
- `telemetry-live` — datos LoRa en vivo a 2 Hz, retención 30 días
- `telemetry-analisis` — datos de SD card a 10 Hz, retención indefinida

### Setup

```bash
cd localDashboard
cp .env.example .env   # llenar con credenciales reales
docker compose up -d
```

- InfluxDB → http://localhost:8086
- Grafana  → http://localhost:3000 (dashboards cargados automáticamente)

---

## Local Dashboard Usage

### 1. Iniciar el stack

```bash
cd localDashboard
docker compose up -d
```

En el primer arranque InfluxDB crea ambos buckets (`telemetry-live` y `telemetry-analisis`) automáticamente vía el script `influxdb/init/create-buckets.sh`.

### 2. Receptor LoRa en vivo

`--run_id` y `--test` son obligatorios y se escriben como tags en cada punto.

```bash
# Windows
python3 laptop/lora_receiver_local.py --port COM3 --run_id run_042 --test suspension_rocks

# Linux / Mac
python3 laptop/lora_receiver_local.py --port /dev/ttyUSB0 --run_id run_042 --test suspension_rocks
```

Argumentos:

| Argumento | Descripción | Ejemplo |
|---|---|---|
| `--port` | Puerto serial | `COM3` / `/dev/ttyUSB0` |
| `--run_id` | ID de la corrida | `run_042` |
| `--test` | Nombre del test | `suspension_rocks` |
| `--baud` | Baudrate (default: 115200) | `9600` |

### 3. Subir datos de SD card (post-carrera)

Formato esperado del CSV: `sample_idx` como primera columna + campos de sensores como float.

```bash
python3 laptop/sd_upload.py --run_id run_042 --test suspension_rocks --csv /ruta/a/datos.csv
```

El script:
1. Escanea hasta 100 filas del CSV buscando las primeras con sensores activos (descarta filas donde `rpm==0` y `temp==0` — sensores aún no inicializados).
2. Para cada fila válida, consulta el punto LoRa live con el mismo `sample_idx` correspondiente (`sd_idx // 2`, ya que SD va a 10 Hz y LoRa a 5 Hz).
3. Calcula el ancla como `live_ts - sd_idx × 100 ms` para cada par encontrado y toma la mediana.
4. Aborta solo si no se encontró ninguna coincidencia entre CSV y live (run/test incorrecto, o SD y LoRa no tienen overlap temporal).
5. Inserta todos los puntos en `telemetry-analisis` con timestamps a 10 Hz.

### 4. Seleccionar corrida y test en Grafana

Ambos dashboards tienen tres variables en la parte superior:

| Variable | Descripción |
|---|---|
| **Measurement** | Nombre del measurement en InfluxDB. Se puebla automáticamente con los measurements disponibles en el bucket. Debe coincidir con `INFLUX_MEASUREMENT` de tu `.env`. |
| **Run ID** | ID de la corrida (`--run_id` del script). Soporta multi-selección para comparar runs. |
| **Test** | Nombre del test (`--test` del script). |

> **Distinción clave:** `INFLUX_MEASUREMENT` en `.env` es el nombre con el que los scripts *escriben* los datos. El filtro **Measurement** en Grafana es con el que los dashboards *leen* esos mismos datos. Si el script escribe `minibaja` y Grafana filtra por `minibaja`, los paneles muestran datos. Si no coinciden, los paneles quedan vacíos.  
> Esto permite usar el mismo stack sin tocar código: un equipo Minibaja pone `INFLUX_MEASUREMENT=minibaja`, uno de Formula pone `INFLUX_MEASUREMENT=formula`, y los dashboards funcionan igual para ambos.

Los dashboards disponibles son:

| Dashboard | Bucket | Uso |
|---|---|---|
| **Live Telemetry** | `telemetry-live` | Monitoreo en carrera, 2 Hz |
| **Post-Race Analysis** | `telemetry-analisis` | Análisis post-carrera, 10 Hz |

En el dashboard Post-Race Analysis:
- El panel **Overlay** superpone datos LoRa y SD del mismo run en el mismo eje temporal.
- El panel **Comparación multi-corrida** muestra una línea por `run_id`; selecciona varios runs en el filtro.
- El panel **Estadísticas** muestra max, min y avg de cada campo para el run seleccionado.

---

### Simulador (sin hardware)

Requiere par de puertos seriales virtuales:
- **Windows** — [com0com](https://sourceforge.net/projects/com0com/), crea par COM10↔COM11
- **Linux** — `socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1`

```bash
python3 laptop/dataSimulator/lora_serial_sim.py --port COM10
python3 laptop/lora_receiver_local.py --port COM11 --run_id sim_001 --test simulacion
```

Flags del simulador:
```
--lat 43.7347    Latitud central de la pista (default: Mónaco)
--lng 7.4206     Longitud central de la pista (default: Mónaco)
--rate 2         Hz de envío (default: 2, igual que LoRa real)
--noise          Agrega líneas de debug del ESP32
```

### Detener

```bash
docker compose down   # los datos persisten en volúmenes Docker
```

---

## Stack Live — con internet

InfluxDB Cloud + Grafana Cloud. Sin Docker. El ESP32 del vehículo escribe directamente a la nube via WiFi (hotspot del celular) — no se necesita laptop en pits.

### Setup

```bash
cd liveDashboard
cp .env.example .env   # llenar con credenciales reales (para el simulador)
```

### Firmware

1. Llena `firmware/transmitter/config.h` con las credenciales de InfluxDB Cloud y la red WiFi.
2. Flashea `firmware/transmitter/transmitter.ino` al ESP32 del vehículo.
3. El ESP32 se conecta automáticamente al hotspot al encenderse.

Ver `liveDashboard/firmware/README.md` para instrucciones detalladas.

### Simulador (sin hardware)

La pista y el nombre del equipo se toman de `liveDashboard/.env` (`TRACK_LAT`, `TRACK_LNG`, `TEAM_NAME`).

```bash
cd liveDashboard
python3 dataSimulator/simulator.py
python3 dataSimulator/simulator.py --rate 5                # 5 Hz
python3 dataSimulator/simulator.py --target influx         # solo InfluxDB
python3 dataSimulator/simulator.py --target mqtt           # solo MQTT
```

---

## Dashboards en Grafana

El proceso es idéntico para el stack local y el stack live. La única diferencia es la URL de Grafana y la datasource configurada.

| Stack | URL Grafana | Datasource |
|---|---|---|
| Local | http://localhost:3000 | InfluxDB local (Docker) |
| Live | https://grafana.com (cloud) | InfluxDB Cloud |

### Campos disponibles

Todos los paneles consultan el measurement definido en `.env` (`INFLUX_MEASUREMENT`, por defecto `coche`) y el bucket `INFLUX_BUCKET`. Campos disponibles:

| Campo | Tipo | Descripción |
|---|---|---|
| `rpm` | float | Revoluciones del motor |
| `speed` | float | Velocidad (km/h) |
| `temp` | float | Temperatura motor (°C) |
| `temp_cvt` | float | Temperatura CVT (°C) |
| `vbat` | float | Voltaje de batería (V) |
| `suspension` | float | Desplazamiento suspensión (m) |
| `throttle` | float | Posición del acelerador (%) |
| `lat` / `lng` | float | Coordenadas GPS (solo con `gps_fix=1`) |
| `lap` | int | Número de vuelta |

Tags: `device=vehicle`, `team=<TEAM_NAME>`.

---

### Crear paneles desde la UI

1. Abre Grafana → **Dashboards → New Dashboard → Add visualization**.
2. Selecciona la datasource de InfluxDB y elige lenguaje **Flux**.
3. Escribe la query para el campo que quieras graficar. Ejemplos:

**RPM en tiempo real**
```flux
from(bucket: "Telemetry")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "coche")
  |> filter(fn: (r) => r._field == "rpm")
```

**Temperatura motor vs CVT**
```flux
from(bucket: "Telemetry")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "coche")
  |> filter(fn: (r) => r._field == "temp" or r._field == "temp_cvt")
```

**Velocidad máxima por vuelta**
```flux
from(bucket: "Telemetry")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "coche" and r._field == "speed")
  |> aggregateWindow(every: 1m, fn: max)
```

4. Ajusta el tipo de panel (Time series, Gauge, Stat, Geomap para GPS).
5. Guarda el panel con un nombre descriptivo.

> Para el mapa GPS usa el panel **Geomap** con los campos `lat` y `lng`. Grafana los reconoce automáticamente si están en la misma fila del resultado Flux — usa un `pivot` si es necesario:
> ```flux
> |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
> |> filter(fn: (r) => exists r.lat and exists r.lng)
> ```

---

### Exportar e importar dashboards como JSON (código)

Grafana permite guardar dashboards completos en JSON para versionarlos o compartirlos.

**Exportar desde la UI:**
1. Abre el dashboard → menú (⋮) → **Share → Export → Save to file**.
2. Guarda el `.json` en `localDashboard/grafana/provisioning/dashboards/` o en `liveDashboard/grafana/dashboards/`.

**Importar desde JSON:**
1. Grafana → **Dashboards → Import → Upload JSON file**.
2. Selecciona el archivo y elige la datasource correcta cuando se pida.

**Provisionar automáticamente al arrancar (solo stack local):**

Crea el archivo `localDashboard/grafana/provisioning/dashboards/dashboards.yml`:
```yaml
apiVersion: 1
providers:
  - name: MadRams
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

Monta la carpeta en `docker-compose.yml`:
```yaml
grafana:
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning
```

Al hacer `docker compose up`, Grafana carga los JSON automáticamente y los dashboards aparecen listos sin tocar la UI.

> Los archivos `*.json` de dashboards están en `.gitignore` por defecto. Si quieres versionarlos, quita esa línea del `.gitignore` del stack correspondiente.

---

## Dashboard HTML — sin Docker *(en desarrollo)*

Dashboard standalone en HTML/JS que se conecta vía WebSocket MQTT (HiveMQ) para mostrar telemetría con baja latencia. Sin Docker, sin instalación — solo abrir en el navegador.

---

## Formato JSON del ESP32

Todos los stacks esperan el mismo formato por serial:

```json
{"msg_id":42,"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,"gps_fix":1,"lap":3,"throttle":60}
```

Campos mínimos requeridos: `rpm`, `temp`. `msg_id` es un contador monotónico por arranque del ESP32; se usa para asignar timestamps deterministas (`t_anchor + msg_id × 200 ms`) y para deduplicar paquetes duplicados. Las coordenadas GPS vienen del sensor del vehículo cuando `gps_fix=1`.

---

## Credenciales

Las credenciales van en archivos `.env` — nunca en el código ni en el repo.
Cada stack tiene su propio `.env` basado en `.env.example`.

Si eres nuevo en el equipo: copia `.env.example` a `.env` en cada carpeta y pide las credenciales al líder de telemetría.

---

## Firmware ESP32

Cada stack tiene su propia carpeta de firmware:

| Stack | Carpeta | Descripción |
|---|---|---|
| Local | `localDashboard/firmware/` | TX (coche) + RX (pits) via LoRa 915 MHz |
| Live | `liveDashboard/firmware/` | Solo TX; envía directo a InfluxDB Cloud via WiFi |

El stack local tiene dos variantes de implementación:

| Variante | Estado | Descripción |
|---|---|---|
| `localDashboard/firmware/arduino/` | **Completo** | Arduino + FreeRTOS. Listo para flashear. |
| `localDashboard/firmware/cpp/` | Esqueleto | ESP-IDF nativo (C++). Estructura y tasks completos; inicialización de drivers con TODOs. |

Ver `localDashboard/firmware/README.md` para instrucciones de setup, arquitectura de tasks y selección de SF/BW.
Ver `liveDashboard/firmware/README.md` para el setup del firmware live.

---

## Notas de arquitectura

**Firmware — RTOS:** El transmisor corre tres FreeRTOS tasks: `taskSampler` (10 Hz, core 1), `taskLoRaSend` (5 Hz, core 0), `taskSDWrite` (10 Hz, core 1). LoRa en core 0 evita que el tiempo de transmisión (~70 ms a SF7/BW500) afecte el muestreo en core 1.

**Firmware — dual SPI:** LoRa usa VSPI (pines 18/19/23) y la SD usa HSPI (14/12/13). Al ser buses independientes no se necesita mutex entre tasks.

**Timestamps deterministas:** `lora_receiver_local.py` asigna timestamps de InfluxDB como `t_anchor + msg_id × 200 ms`. Si el receptor arranca tarde, el anchor se extrapola hacia atrás para que la rejilla de tiempos sea consistente desde el primer paquete. Los paquetes tardíos se insertan retroactivamente (InfluxDB acepta escrituras fuera de orden); solo los duplicados exactos se descartan.

**HiveMQ** es exclusivo del dashboard HTML — publica los datos vía WebSocket MQTT para la visualización de baja latencia. El stack live estándar no lo requiere.

**Buffer offline** — `lora_receiver_local.py` mantiene hasta 1000 puntos en RAM si InfluxDB no responde, y los reenvía automáticamente al reconectar.

**Weather data** — el simulador live obtiene datos de [Open-Meteo](https://open-meteo.com/) sin API key y los guarda como measurement `weather` para correlacionar condiciones con telemetría.
