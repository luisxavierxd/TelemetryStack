# MadRams Telemetry — Minibaja SAE

Sistema de telemetría en tiempo real para el vehículo Minibaja SAE del equipo MadRams.
Tres stacks independientes según disponibilidad de internet y necesidades en pits.

```
ESP32 LoRa TX ──915MHz──► ESP32 LoRa RX ──USB──► Python receiver ──► InfluxDB ──► Grafana
    (coche)                   (pits)
                                         └─ localDashboard/   Docker local      (sin internet)
                                         └─ liveDashboard/    Cloud             (con internet) [en desarrollo]
                                         └─ htmlDashboard/    HTML standalone   (sin Docker)  [en desarrollo]
```

---

## Estructura del repositorio

```
MadRamsTelemetry/
├── README.md
├── LICENSE
├── .gitignore
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
python3 dataSimulator/lora_serial_sim.py --port COM10        # terminal 1
python3 lora_receiver_local.py --port COM11                  # terminal 2
```

Flags:
```
--rate 2     Hz de envío (default: 2, igual que LoRa real)
--noise      Agrega líneas de debug del ESP32
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
python3 lora_receiver_live.py --port COM3                  # ambos destinos
python3 lora_receiver_live.py --port COM3 --target influx  # solo InfluxDB Cloud
python3 lora_receiver_live.py --port COM3 --target mqtt    # solo HiveMQ
```

### Simulador

```bash
python3 dataSimulator/simulator.py                         # ambos destinos
python3 dataSimulator/simulator.py --target influx
python3 dataSimulator/simulator.py --target mqtt
python3 dataSimulator/simulator.py --rate 5                # 5 Hz
```

---

## Dashboard HTML — sin Docker *(en desarrollo)*

Dashboard standalone en HTML/JS que se conecta directamente vía WebSocket MQTT (HiveMQ) para mostrar telemetría con baja latencia, sin necesidad de Docker ni Grafana.

Útil para competencias donde la latencia de Grafana Cloud (~1-2s) no es suficiente o donde no se puede instalar Docker.

---

## Formato JSON del ESP32

Ambos stacks esperan el mismo formato por serial:

```json
{"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,"gps_fix":1,"lap":3,"throttle":60}
```

Campos mínimos requeridos: `rpm`, `temp`. Cualquier otra línea se ignora.

---

## Credenciales

Las credenciales van en archivos `.env` — nunca en el código ni en el repo.
Cada stack tiene su propio `.env` basado en `.env.example`.

```
localDashboard/.env   → INFLUX_TOKEN, INFLUX_PASSWORD, GF_PASSWORD
liveDashboard/.env    → token InfluxDB Cloud, credenciales HiveMQ
```

Si eres nuevo en el equipo: copia `.env.example` a `.env` en cada carpeta y pide las credenciales al líder de telemetría.

---

## Notas de arquitectura

**HiveMQ** está integrado en el stack live pero es opcional (`--target influx` lo omite). Su propósito es alimentar el dashboard HTML via WebSocket MQTT.

**Weather data** — el simulador live obtiene datos de [Open-Meteo](https://open-meteo.com/) sin API key y los guarda en InfluxDB como measurement `weather` para correlacionar condiciones con telemetría.

**Buffer offline** — `lora_receiver_local.py` mantiene hasta 1000 puntos en RAM si InfluxDB no responde, y los reenvía automáticamente al reconectar.
