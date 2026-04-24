# TelemetryStack — SAE Telemetry System

Desarrollado por **Luis Xavier García Pimentel Ascencio**.
Stack de telemetría en tiempo real para vehículos SAE (Minibaja, Formula, Baja). Diseñado para ser adoptado por cualquier equipo con configuración mínima.

```
ESP32 LoRa TX ──915MHz──► ESP32 LoRa RX ──USB──► Python receiver ──► InfluxDB ──► Grafana
    (coche)                   (pits)
                                         └─ localDashboard/   Docker local      (sin internet)
                                         └─ liveDashboard/    Cloud             (con internet)
                                         └─ htmlDashboard/    HTML standalone   (sin Docker)  [en desarrollo]
```

---

## Estructura del repositorio

```
TelemetryStack/
├── README.md
├── LICENSE
├── .gitignore
├── .gitattributes
├── localDashboard/
│   ├── .env                        ← credenciales reales (NO commitear)
│   ├── .env.example                ← plantilla para nuevos miembros
│   ├── docker-compose.yml
│   ├── lora_receiver_local.py      ← serial → InfluxDB local
│   ├── grafana/
│   │   └── provisioning/
│   │       └── datasources/
│   │           └── influxdb.yml
│   └── dataSimulator/
│       └── lora_serial_sim.py      ← simula ESP32 por serial virtual
├── liveDashboard/                  ← en desarrollo
│   ├── .env                        ← credenciales reales (NO commitear)
│   ├── .env.example                ← plantilla para nuevos miembros
│   ├── lora_receiver_live.py       ← serial → InfluxDB Cloud + HiveMQ
│   └── dataSimulator/
│       └── simulator.py            ← simula vehículo → nube
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
| `INFLUX_MEASUREMENT` | Nombre del measurement (tipo de vehículo) | `coche` | ambos |
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

InfluxDB + Grafana corren en Docker en la laptop de pits.

### Setup

```bash
cd localDashboard
cp .env.example .env   # llenar con credenciales reales
docker compose up -d
```

- InfluxDB → http://localhost:8086
- Grafana  → http://localhost:3000

### Receptor

```bash
# Windows
python3 lora_receiver_local.py --port COM3

# Linux / Mac
python3 lora_receiver_local.py --port /dev/ttyUSB0
```

El script carga el token automáticamente desde `localDashboard/.env`.

### Simulador (sin hardware)

Requiere par de puertos seriales virtuales:
- **Windows** — [com0com](https://sourceforge.net/projects/com0com/), crea par COM10↔COM11
- **Linux** — `socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1`

```bash
# Default: Mónaco. Cambia la pista con --lat y --lng
python3 dataSimulator/lora_serial_sim.py --port COM10
python3 lora_receiver_local.py --port COM11
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

InfluxDB Cloud + Grafana Cloud. Sin Docker.

### Setup

```bash
cd liveDashboard
cp .env.example .env   # llenar con credenciales reales
```

### Receptor

```bash
python3 lora_receiver_live.py --port COM3                  # Windows
python3 lora_receiver_live.py --port /dev/ttyUSB0          # Linux / Mac
```

### Simulador

La pista y el nombre del equipo se toman de `liveDashboard/.env` (`TRACK_LAT`, `TRACK_LNG`, `TEAM_NAME`).

```bash
python3 dataSimulator/simulator.py
python3 dataSimulator/simulator.py --rate 5                # 5 Hz
python3 dataSimulator/simulator.py --target influx         # solo InfluxDB
python3 dataSimulator/simulator.py --target mqtt           # solo MQTT
```

---

## Dashboard HTML — sin Docker *(en desarrollo)*

Dashboard standalone en HTML/JS que se conecta vía WebSocket MQTT (HiveMQ) para mostrar telemetría con baja latencia. Sin Docker, sin instalación — solo abrir en el navegador.

---

## Formato JSON del ESP32

Todos los stacks esperan el mismo formato por serial:

```json
{"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,"gps_fix":1,"lap":3,"throttle":60}
```

Campos mínimos requeridos: `rpm`, `temp`. Las coordenadas GPS vienen del sensor del vehículo cuando `gps_fix=1`.

---

## Credenciales

Las credenciales van en archivos `.env` — nunca en el código ni en el repo.
Cada stack tiene su propio `.env` basado en `.env.example`.

Si eres nuevo en el equipo: copia `.env.example` a `.env` en cada carpeta y pide las credenciales al líder de telemetría.

---

## Notas de arquitectura

**HiveMQ** es exclusivo del dashboard HTML — publica los datos vía WebSocket MQTT para la visualización de baja latencia. El stack live estándar no lo requiere.

**Buffer offline** — `lora_receiver_local.py` mantiene hasta 1000 puntos en RAM si InfluxDB no responde, y los reenvía automáticamente al reconectar.

**Weather data** — el simulador live obtiene datos de [Open-Meteo](https://open-meteo.com/) sin API key y los guarda como measurement `weather` para correlacionar condiciones con telemetría.
