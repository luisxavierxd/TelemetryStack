# Stack Live — Con Internet

Stack de telemetría en tiempo real que no requiere laptop en pits. El ESP32 del vehículo escribe directamente a InfluxDB Cloud via WiFi (hotspot del celular).

```
ESP32 TX (coche)
  ─── WiFi ───►
                Hotspot (celular)
                  ─── Internet ───►
                                    InfluxDB Cloud
                                      ─── datasource ───►
                                                          Grafana Cloud
```

Sin Docker. Sin laptop. Sin receptor ESP32. Solo el coche, el celular, y la nube.

---

## Diferencias con el stack local

| Aspecto | Local | Live |
|---|---|---|
| Conectividad | LoRa 915 MHz | WiFi → hotspot celular |
| ESP32s | 2 (TX en coche + RX en pits) | 1 (solo TX en coche) |
| Laptop en pits | Sí | No |
| Base de datos | InfluxDB en Docker (local) | InfluxDB Cloud |
| Dashboards | Grafana en Docker (local) | Grafana Cloud |
| Timestamps | Deterministas por `msg_id` | Wall-clock via NTP |
| SD card backup | Sí (10 Hz) | No |
| Post-análisis | `sd_upload.py` | No aplica |

---

## Estructura

```
liveDashboard/
├── firmware/                   ← firmware del ESP32 TX
│   ├── README.md               ← instrucciones de flasheo y config.h
│   └── transmitter/
│       ├── transmitter.ino     ← completo, listo para flashear
│       ├── config.h.example    ← plantilla de configuración
│       └── config.h            ← gitignored, llenar con valores reales
├── dataSimulator/
│   └── simulator.py            ← simula el vehículo → InfluxDB Cloud / MQTT
├── .env                        ← credenciales reales (NO commitear)
└── .env.example                ← plantilla
```

---

## Requisitos

- Cuenta en **InfluxDB Cloud** (free tier disponible en [influxdata.com](https://cloud2.influxdata.com))
- Cuenta en **Grafana Cloud** (free tier disponible en [grafana.com](https://grafana.com))
- ESP32 con módulo WiFi (cualquier variante estándar)
- Celular con datos móviles y hotspot activado
- **Python 3.10+** (solo para el simulador)

```bash
pip install influxdb-client python-dotenv paho-mqtt requests
```

---

## Setup inicial

### 1. InfluxDB Cloud

1. Crea una cuenta en [cloud2.influxdata.com](https://cloud2.influxdata.com).
2. Crea una organización y un bucket llamado `Telemetry` (retención libre).
3. Ve a **Load Data → API Tokens → Generate API Token → All Access Token** y copia el token.
4. Anota la URL de tu instancia (ej. `https://us-east-1-1.aws.cloud2.influxdata.com`).

### 2. Grafana Cloud

1. Crea una cuenta en [grafana.com](https://grafana.com).
2. En tu stack de Grafana Cloud, ve a **Connections → Add new connection → InfluxDB**.
3. Configura la datasource:
   - Query language: **Flux**
   - URL: la URL de tu instancia de InfluxDB Cloud
   - Token: el token que generaste
   - Organization: el nombre de tu organización
   - Default bucket: `Telemetry`
4. Guarda y verifica la conexión.

### 3. Credenciales locales (para el simulador)

```bash
cp .env.example .env
```

Edita `.env`:

| Variable | Descripción |
|---|---|
| `INFLUX_URL` | URL de tu instancia InfluxDB Cloud |
| `INFLUX_TOKEN` | API token de InfluxDB Cloud |
| `INFLUX_ORG` | Nombre de tu organización (o email de la cuenta) |
| `INFLUX_BUCKET` | Bucket de datos (default `Telemetry`) |
| `INFLUX_MEASUREMENT` | Nombre del measurement (ej. `minibaja`, `formula`) |
| `TEAM_NAME` | Tag del equipo en cada punto |
| `TRACK_LAT` | Latitud central de la pista (simulador) |
| `TRACK_LNG` | Longitud central de la pista (simulador) |
| `MQTT_HOST` | Host de HiveMQ (solo para dashboard HTML) |
| `MQTT_PORT` | Puerto MQTT TLS (default `8883`) |
| `MQTT_USER` | Usuario MQTT |
| `MQTT_PASS` | Password MQTT |

### 4. Firmware

1. Copia y llena `firmware/transmitter/config.h`:
   ```bash
   cd firmware/transmitter
   cp config.h.example config.h
   # Edita config.h con tus credenciales y pines
   ```

2. Abre `transmitter.ino` en Arduino IDE y flashea al ESP32.

Ver `firmware/README.md` para instrucciones detalladas de setup de Arduino IDE y descripción de cada campo de `config.h`.

---

## Uso en carrera

### Arranque

1. Activa el hotspot en el celular con el SSID y password configurados en `config.h`.
2. Enciende el ESP32 del vehículo.
3. El ESP32:
   - Se conecta automáticamente al hotspot
   - Sincroniza la hora por NTP (`pool.ntp.org`)
   - Verifica la conexión con InfluxDB Cloud
   - Comienza a escribir datos a 5 Hz

El output del monitor serial muestra el estado de conexión:
```
[boot] MadRams Live Transmitter
[wifi] connecting......
[wifi] OK — 192.168.x.x
[influx] OK — https://us-east-1-1.aws.cloud2.influxdata.com
```

### Durante la carrera

El firmware corre dos FreeRTOS tasks:

| Task | Core | Frecuencia | Función |
|---|---|---|---|
| `taskSampler` | 1 | 10 Hz | Lee sensores, actualiza estado compartido |
| `taskSend` | 0 | 5 Hz | Lee estado, escribe a InfluxDB Cloud vía HTTPS |

Si el WiFi se corta (coche fuera de alcance del hotspot), `taskSend` detecta la desconexión y reintenta automáticamente cada segundo. Los puntos que no se pudieron escribir se pierden — no hay buffer offline como en el stack local. Para minimizar pérdidas, mantén el celular en un lugar con buena línea de vista al circuito.

### Ver datos en Grafana Cloud

Abre tu instancia de Grafana Cloud y crea o importa dashboards con la datasource de InfluxDB Cloud configurada. Los datos aparecen con el tag `device=vehicle` y `team=<TEAM_NAME>`.

Campos disponibles:

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

---

## Simulador (sin hardware)

Simula el vehículo y publica datos a InfluxDB Cloud y/o HiveMQ MQTT. Útil para probar dashboards y la datasource sin tener el coche conectado.

Las credenciales se leen automáticamente del `.env`. También se pueden pasar como flags para sobreescribir el `.env`.

```bash
cd liveDashboard

# Ambos destinos (default)
python3 dataSimulator/simulator.py

# Solo InfluxDB Cloud
python3 dataSimulator/simulator.py --target influx

# Solo MQTT
python3 dataSimulator/simulator.py --target mqtt

# Cambiar frecuencia
python3 dataSimulator/simulator.py --rate 5
```

Flags completos:

| Flag | Descripción | Default |
|---|---|---|
| `--target` | Destino: `influx`, `mqtt`, o `both` | `both` |
| `--rate` | Hz de publicación | `10` |
| `--weather-interval` | Segundos entre fetch de clima (Open-Meteo) | `60` |
| `--influx-url` | Override URL de InfluxDB | desde `.env` |
| `--influx-token` | Override token de InfluxDB | desde `.env` |
| `--influx-org` | Override org de InfluxDB | desde `.env` |
| `--influx-bucket` | Override bucket | desde `.env` |
| `--mqtt-host` | Override host MQTT | desde `.env` |
| `--mqtt-port` | Override puerto MQTT | `8883` |
| `--mqtt-user` | Override usuario MQTT | desde `.env` |
| `--mqtt-pass` | Override password MQTT | desde `.env` |

El simulador también publica datos de clima en tiempo real desde [Open-Meteo](https://open-meteo.com/) (sin API key) como measurement `weather`, para correlacionar condiciones ambientales con la telemetría del vehículo.

Output en consola:
```
[accel ] RPM:2847  Speed: 31.4km/h  Temp: 78.3°C  CVT: 71.2°C  Vbat:12.18V  Lap:0  INFLUX:OK  MQTT:ON
[cruise] RPM:2100  Speed: 35.0km/h  Temp: 82.1°C  CVT: 74.8°C  Vbat:12.32V  Lap:1  INFLUX:OK  MQTT:ON
```

---

## Troubleshooting

**El ESP32 no conecta al WiFi**
- Verifica que `WIFI_SSID` y `WIFI_PASSWORD` en `config.h` coincidan exactamente con el hotspot.
- El SSID es case-sensitive.
- Algunos celulares deshabilitan el hotspot tras unos minutos sin clientes — actívalo antes de encender el ESP32.

**El ESP32 conecta al WiFi pero falla en InfluxDB**
- Verifica que `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, e `INFLUX_BUCKET` en `config.h` sean correctos.
- El token debe tener permisos de escritura sobre el bucket.
- Confirma que el bucket `Telemetry` exista en tu organización de InfluxDB Cloud.

**Grafana no muestra datos**
- Verifica que la datasource apunte a la misma organización y bucket donde el ESP32 está escribiendo.
- Revisa que el filtro de measurement en la query coincida con `INFLUX_MEASUREMENT` de tu `config.h` (`INFLUX_MEASUREMENT` define).
- En InfluxDB Cloud, ve a **Data Explorer** y busca datos recientes para confirmar que están llegando.

**El simulador falla con error de credenciales**
- Verifica que `.env` exista y tenga los valores correctos (no el `.env.example`).
- Si pasas flags por CLI, asegúrate de que todos los requeridos estén presentes (`--influx-url`, `--influx-token`, `--influx-org` para InfluxDB; `--mqtt-host`, `--mqtt-user`, `--mqtt-pass` para MQTT).

---

## Notas de arquitectura

**Timestamps wall-clock** — a diferencia del stack local, los timestamps son la hora real del sistema sincronizada por NTP. El ESP32 llama a `timeSync()` en el setup y la librería `InfluxDBClient` estampa cada punto con el tiempo actual al momento de llamar `writePoint()`. No hay contador `msg_id` ni anchor — si hay jitter de red, el punto llega tarde pero con timestamp correcto.

**Sin buffer offline** — si la conexión a InfluxDB se interrumpe, los puntos de ese periodo se pierden. La librería `InfluxDBClient` tiene reintentos internos, pero no mantiene buffer persistente entre ciclos de `taskSend`. Para sesiones críticas, considera correr el stack local en paralelo como respaldo.

**NTP requerido** — InfluxDB Cloud rechaza puntos con timestamps muy desviados del tiempo real. Si el ESP32 no puede sincronizar NTP al arrancar (sin internet en ese momento), los timestamps serán incorrectos. Asegúrate de que el hotspot tenga datos antes de encender el ESP32.

**HiveMQ MQTT** — el simulador puede publicar a HiveMQ vía TLS para alimentar el dashboard HTML standalone. El firmware del ESP32 no incluye publicación MQTT — si se necesita en hardware, habría que agregar la librería `PubSubClient` o `AsyncMqttClient` al `transmitter.ino`.
