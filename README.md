> 🇺🇸 English · [🇲🇽 Español](README.es.md)

# TelemetryStack — SAE Telemetry System

Developed by **Luis Xavier García Pimentel Ascencio**.
Real-time telemetry stack for SAE off-road vehicles (Minibaja, Formula, Baja). Designed to be adopted by any team with minimal configuration.

**Local stack (no internet):**
```
ESP32 LoRa TX ──915MHz──► ESP32 LoRa RX ──USB──► lora_receiver_local.py ──► InfluxDB (Docker) ──► Grafana
    (vehicle)                  (pits)                  localDashboard/laptop/
```

**Live stack (internet required):**
```
ESP32 ──WiFi──► Phone hotspot ──Internet──► InfluxDB Cloud ──► Grafana Cloud
(vehicle)           liveDashboard/firmware/
```

**HTML Dashboard** *(in development)* — standalone, no Docker, via WebSocket MQTT.

---

## Repository Structure

```
TelemetryStack/
├── README.md                       ← this file (English)
├── README.es.md                    ← Spanish version
├── LICENSE
├── .gitignore
├── .gitattributes
├── localDashboard/
│   ├── README.md                   ← full local stack guide
│   ├── firmware/                   ← ESP32: TX (vehicle) + RX (pits) via LoRa
│   │   ├── README.md               ← firmware architecture, tasks, SF/BW, config.h
│   │   ├── arduino/                ← complete, ready to flash
│   │   │   ├── transmitter/
│   │   │   │   ├── transmitter.ino
│   │   │   │   ├── config.h.example
│   │   │   │   └── config.h        ← gitignored, fill with real values
│   │   │   └── receiver/
│   │   │       ├── receiver.ino
│   │   │       ├── config.h.example
│   │   │       └── config.h
│   │   └── cpp/                    ← ESP-IDF skeleton (structure + TODOs)
│   │       ├── transmitter/
│   │       └── receiver/
│   ├── laptop/                     ← code to run on the pits laptop
│   │   ├── README.md               ← quick reference for the three scripts
│   │   ├── lora_receiver_local.py  ← serial → local InfluxDB
│   │   ├── sd_upload.py            ← uploads SD card CSV → InfluxDB
│   │   └── dataSimulator/
│   │       └── lora_serial_sim.py  ← simulates ESP32 over virtual serial
│   ├── docker-compose.yml
│   ├── .env                        ← real credentials (DO NOT commit)
│   ├── .env.example                ← template for new team members
│   └── grafana/
│       └── provisioning/
│           └── datasources/
│               └── influxdb.yml
├── liveDashboard/
│   ├── README.md                   ← full live stack guide
│   ├── firmware/                   ← ESP32: TX direct to InfluxDB Cloud via WiFi
│   │   ├── README.md               ← live firmware setup, config.h fields
│   │   └── transmitter/
│   │       ├── transmitter.ino     ← complete, ready to flash
│   │       ├── config.h.example
│   │       └── config.h            ← gitignored, fill with real credentials
│   ├── dataSimulator/
│   │   └── simulator.py            ← simulates vehicle → InfluxDB Cloud
│   ├── .env                        ← real credentials (DO NOT commit)
│   └── .env.example
└── htmlDashboard/                  ← in development
    └── README.md
```

---

## Adapting to Your Team

Only the `.env` file needs to be edited — nothing in the code changes between teams.

```bash
cd localDashboard
cp .env.example .env
```

Variables to customize in `.env`:

| Variable | Description | Example | Stack |
|---|---|---|---|
| `INFLUX_TOKEN` | InfluxDB token | `my-secret-token` | both |
| `INFLUX_PASSWORD` | InfluxDB admin password | `my-password` | local |
| `GF_PASSWORD` | Grafana password | `my-password` | local |
| `INFLUX_ORG` | InfluxDB organization name | `my-team` | both |
| `INFLUX_BUCKET` | Data bucket | `Telemetry` | both |
| `INFLUX_MEASUREMENT` | Measurement name written by Python scripts. Must match the **Measurement** filter in Grafana. Each project uses its own (e.g. Minibaja SAE → `minibaja`, Formula SAE → `formula`). | `minibaja` | both |
| `TEAM_NAME` | Team tag on every data point | `my-team` | both |
| `TRACK_LAT` | Track center latitude (simulator) | `43.734722` | live |
| `TRACK_LNG` | Track center longitude (simulator) | `7.420556` | live |

GPS data in production comes directly from the vehicle's GPS sensor.

---

## General Requirements

- Python 3.10+
- Docker Desktop (local stack only)

```bash
pip install pyserial influxdb-client paho-mqtt python-dotenv requests
```

---

## Local Stack — no internet

InfluxDB + Grafana run in Docker on the pits laptop. Two buckets are created automatically:
- `telemetry-live` — live LoRa data at 2 Hz, 30-day retention
- `telemetry-analisis` — SD card data at 10 Hz, unlimited retention

### Setup

```bash
cd localDashboard
cp .env.example .env   # fill with real credentials
docker compose up -d
```

- InfluxDB → http://localhost:8086
- Grafana  → http://localhost:3000 (dashboards loaded automatically)

---

## Local Dashboard Usage

### 1. Start the stack

```bash
cd localDashboard
docker compose up -d
```

On first boot, InfluxDB creates both buckets (`telemetry-live` and `telemetry-analisis`) automatically via the `influxdb/init/create-buckets.sh` script.

### 2. Live LoRa receiver

`--run_id` and `--test` are required and are written as tags on every data point.

```bash
# Windows
python3 laptop/lora_receiver_local.py --port COM3 --run_id run_042 --test suspension_rocks

# Linux / Mac
python3 laptop/lora_receiver_local.py --port /dev/ttyUSB0 --run_id run_042 --test suspension_rocks
```

Arguments:

| Argument | Description | Example |
|---|---|---|
| `--port` | Serial port | `COM3` / `/dev/ttyUSB0` |
| `--run_id` | Run identifier | `run_042` |
| `--test` | Test name | `suspension_rocks` |
| `--baud` | Baud rate (default: 115200) | `9600` |

### 3. Upload SD card data (post-race)

Expected CSV format: `sample_idx` as the first column + sensor fields as floats.

```bash
python3 laptop/sd_upload.py --run_id run_042 --test suspension_rocks --csv /path/to/data.csv
```

The script:
1. Scans up to 100 CSV rows looking for the first ones with active sensors (skips rows where `rpm==0` and `temp==0` — sensors not yet initialized).
2. For each valid row, queries the live LoRa point with the exact same `sample_idx` (the ESP32 uses a single counter for both `msg_id` in LoRa and `sample_idx` in CSV).
3. Computes the anchor as `live_ts - sd_idx × 100 ms` for each matched pair and takes the median.
4. Aborts only if no match is found between CSV and live data (wrong run/test, or SD and LoRa have no temporal overlap).
5. Inserts all points into `telemetry-analisis` with 10 Hz timestamps.

### 4. Selecting run and test in Grafana

Both dashboards have three variables at the top:

| Variable | Description |
|---|---|
| **Measurement** | InfluxDB measurement name. Auto-populated from available measurements in the bucket. Must match `INFLUX_MEASUREMENT` in your `.env`. |
| **Run ID** | Run identifier (`--run_id` from the script). Supports multi-select to compare runs. |
| **Test** | Test name (`--test` from the script). |

> **Key distinction:** `INFLUX_MEASUREMENT` in `.env` is the name the scripts use to *write* data. The **Measurement** filter in Grafana is what the dashboards use to *read* that data. If the script writes `minibaja` and Grafana filters by `minibaja`, panels show data. If they don't match, panels will be empty.  
> This lets you use the same stack without touching code: a Minibaja team sets `INFLUX_MEASUREMENT=minibaja`, a Formula team sets `INFLUX_MEASUREMENT=formula`, and the dashboards work the same for both.

Available dashboards:

| Dashboard | Bucket | Use |
|---|---|---|
| **Live Telemetry** | `telemetry-live` | In-race monitoring, 2 Hz |
| **Post-Race Analysis** | `telemetry-analisis` | Post-race analysis, 10 Hz |

In the Post-Race Analysis dashboard:
- The **Overlay** panel overlays LoRa and SD data from the same run on the same time axis.
- The **Multi-run comparison** panel shows one line per `run_id`; select multiple runs in the filter.
- The **Statistics** panel shows max, min, and avg for each field for the selected run.

---

### Simulator (no hardware)

Requires a virtual serial port pair:
- **Windows** — [com0com](https://sourceforge.net/projects/com0com/), create pair COM10↔COM11
- **Linux** — `socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1`

```bash
python3 laptop/dataSimulator/lora_serial_sim.py --port COM10
python3 laptop/lora_receiver_local.py --port COM11 --run_id sim_001 --test simulation
```

Simulator flags:
```
--lat 43.7347    Track center latitude (default: Monaco)
--lng 7.4206     Track center longitude (default: Monaco)
--rate 2         Send rate in Hz (default: 2, same as real LoRa)
--noise          Add ESP32-style debug lines
```

### Stop

```bash
docker compose down   # data persists in Docker volumes
```

---

## Live Stack — internet required

InfluxDB Cloud + Grafana Cloud. No Docker. The vehicle ESP32 writes directly to the cloud via WiFi (phone hotspot) — no laptop needed at pits.

### Setup

```bash
cd liveDashboard
cp .env.example .env   # fill with real credentials (for the simulator)
```

### Firmware

1. Fill `firmware/transmitter/config.h` with your InfluxDB Cloud credentials and WiFi network.
2. Flash `firmware/transmitter/transmitter.ino` to the vehicle ESP32.
3. The ESP32 connects automatically to the hotspot on power-up.

See `liveDashboard/firmware/README.md` for detailed instructions.

### Simulator (no hardware)

Track location and team name are read from `liveDashboard/.env` (`TRACK_LAT`, `TRACK_LNG`, `TEAM_NAME`).

```bash
cd liveDashboard
python3 dataSimulator/simulator.py
python3 dataSimulator/simulator.py --rate 5                # 5 Hz
python3 dataSimulator/simulator.py --target influx         # InfluxDB only
python3 dataSimulator/simulator.py --target mqtt           # MQTT only
```

---

## Grafana Dashboards

The process is identical for the local and live stacks. The only difference is the Grafana URL and the configured datasource.

| Stack | Grafana URL | Datasource |
|---|---|---|
| Local | http://localhost:3000 | Local InfluxDB (Docker) |
| Live | https://grafana.com (cloud) | InfluxDB Cloud |

### Available fields

All panels query the measurement defined in `.env` (`INFLUX_MEASUREMENT`, default `coche`) and the bucket `INFLUX_BUCKET`. Available fields:

| Field | Type | Description |
|---|---|---|
| `rpm` | float | Engine RPM |
| `speed` | float | Speed (km/h) |
| `temp` | float | Engine temperature (°C) |
| `temp_cvt` | float | CVT temperature (°C) |
| `vbat` | float | Battery voltage (V) |
| `suspension` | float | Suspension displacement (m) |
| `throttle` | float | Throttle position (%) |
| `lat` / `lng` | float | GPS coordinates (only when `gps_fix=1`) |
| `lap` | int | Lap number |

Tags: `device=vehicle`, `team=<TEAM_NAME>`.

---

### Creating panels from the UI

1. Open Grafana → **Dashboards → New Dashboard → Add visualization**.
2. Select the InfluxDB datasource and choose **Flux** as the query language.
3. Write the query for the field you want to chart. Examples:

**Real-time RPM**
```flux
from(bucket: "Telemetry")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "coche")
  |> filter(fn: (r) => r._field == "rpm")
```

**Engine temp vs CVT temp**
```flux
from(bucket: "Telemetry")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "coche")
  |> filter(fn: (r) => r._field == "temp" or r._field == "temp_cvt")
```

**Max speed per lap**
```flux
from(bucket: "Telemetry")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "coche" and r._field == "speed")
  |> aggregateWindow(every: 1m, fn: max)
```

4. Adjust the panel type (Time series, Gauge, Stat, Geomap for GPS).
5. Save the panel with a descriptive name.

> For the GPS map use the **Geomap** panel with `lat` and `lng` fields. Grafana recognizes them automatically if they are in the same Flux result row — use a `pivot` if needed:
> ```flux
> |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
> |> filter(fn: (r) => exists r.lat and exists r.lng)
> ```

---

### Exporting and importing dashboards as JSON

Grafana lets you save complete dashboards as JSON for versioning or sharing.

**Export from the UI:**
1. Open the dashboard → menu (⋮) → **Share → Export → Save to file**.
2. Save the `.json` in `localDashboard/grafana/provisioning/dashboards/` or `liveDashboard/grafana/dashboards/`.

**Import from JSON:**
1. Grafana → **Dashboards → Import → Upload JSON file**.
2. Select the file and choose the correct datasource when prompted.

**Auto-provision on startup (local stack only):**

Create `localDashboard/grafana/provisioning/dashboards/dashboards.yml`:
```yaml
apiVersion: 1
providers:
  - name: MadRams
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

Mount the folder in `docker-compose.yml`:
```yaml
grafana:
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning
```

On `docker compose up`, Grafana loads the JSON files automatically and dashboards appear ready without touching the UI.

> Dashboard `*.json` files are gitignored by default. To version them, remove that line from the relevant stack's `.gitignore`.

---

## HTML Dashboard — no Docker *(in development)*

Standalone HTML/JS dashboard that connects via WebSocket MQTT (HiveMQ) to display telemetry with low latency. No Docker, no installation — just open in a browser.

---

## ESP32 JSON Format

All stacks expect the same serial format:

```json
{"msg_id":42,"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,"gps_fix":1,"lap":3,"throttle":60}
```

Minimum required fields: `rpm`, `temp`. `msg_id` is a monotonic counter per ESP32 boot; it is used to assign deterministic timestamps (`t_anchor + msg_id × 200 ms`) and to discard duplicate packets. GPS coordinates are written only when `gps_fix=1`.

---

## Credentials

Credentials go in `.env` files — never in code or in the repo.
Each stack has its own `.env` based on `.env.example`.

If you're new to the team: copy `.env.example` to `.env` in each folder and ask the telemetry lead for the credentials.

---

## ESP32 Firmware

Each stack has its own firmware folder:

| Stack | Folder | Description |
|---|---|---|
| Local | `localDashboard/firmware/` | TX (vehicle) + RX (pits) via LoRa 915 MHz |
| Live | `liveDashboard/firmware/` | TX only; writes directly to InfluxDB Cloud via WiFi |

The local stack has two implementation variants:

| Variant | Status | Description |
|---|---|---|
| `localDashboard/firmware/arduino/` | **Complete** | Arduino + FreeRTOS. Ready to flash. |
| `localDashboard/firmware/cpp/` | Skeleton | Native ESP-IDF (C++). Task structure complete; driver initialization marked TODO. |

See `localDashboard/firmware/README.md` for setup instructions, task architecture, and SF/BW selection.
See `liveDashboard/firmware/README.md` for live firmware setup.

---

## Architecture Notes

**Firmware — RTOS:** The transmitter runs three FreeRTOS tasks: `taskSampler` (10 Hz, core 1), `taskLoRaSend` (5 Hz, core 0), `taskSDWrite` (10 Hz, core 1). Running LoRa on core 0 prevents the ~70 ms transmission time (at SF7/BW500) from affecting sensor sampling on core 1.

**Firmware — dual SPI:** LoRa uses VSPI (pins 18/19/23) and SD uses HSPI (14/12/13). Independent buses mean no mutex is needed between tasks.

**Deterministic timestamps:** `lora_receiver_local.py` assigns InfluxDB timestamps as `t_anchor + msg_id × 200 ms`. If the receiver starts late, the anchor is extrapolated backward so the time grid is consistent from the first packet. Late packets are inserted retroactively (InfluxDB accepts out-of-order writes); only exact duplicates are discarded.

**HiveMQ** is exclusive to the HTML dashboard — it publishes data via WebSocket MQTT for low-latency visualization. The standard live stack does not require it.

**Offline buffer** — `lora_receiver_local.py` keeps up to 1000 points in RAM if InfluxDB is unreachable, and flushes them automatically on reconnect.

**Weather data** — the live simulator fetches data from [Open-Meteo](https://open-meteo.com/) without an API key and stores it as the `weather` measurement to correlate conditions with telemetry.
