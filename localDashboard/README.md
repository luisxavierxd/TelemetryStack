# Stack Local — Sin Internet

Stack completo de telemetría en tiempo real para vehículos SAE, sin depender de internet. Todo corre en la laptop de pits.

```
ESP32 TX (coche)
  ─── LoRa 915 MHz ───►
                        ESP32 RX (pits)
                          ─── USB serial ───►
                                              lora_receiver_local.py
                                                ─── HTTP ───►
                                                              InfluxDB :8086 (Docker)
                                                                ─── datasource ───►
                                                                                    Grafana :3000 (Docker)
```

Dos buckets en InfluxDB:

| Bucket | Fuente | Frecuencia | Retención |
|---|---|---|---|
| `telemetry-live` | `lora_receiver_local.py` vía radio | 5 Hz | 30 días |
| `telemetry-analisis` | `sd_upload.py` desde CSV de SD card | 10 Hz | indefinida |

---

## Estructura

```
localDashboard/
├── firmware/                   ← firmware del ESP32 TX y RX
│   ├── README.md               ← arquitectura de tasks, SF/BW, config.h
│   ├── arduino/                ← completo, listo para flashear
│   │   ├── transmitter/
│   │   └── receiver/
│   └── cpp/                    ← esqueleto ESP-IDF (TODOs en drivers)
│       ├── transmitter/
│       └── receiver/
├── laptop/                     ← código a correr en la laptop de pits
│   ├── lora_receiver_local.py  ← receptor serial → InfluxDB
│   ├── sd_upload.py            ← subida de CSV de SD card → InfluxDB
│   └── dataSimulator/
│       └── lora_serial_sim.py  ← simula el ESP32 TX por serial virtual
├── grafana/
│   └── provisioning/
│       ├── dashboards/         ← JSONs de dashboards (Grafana los carga al iniciar)
│       └── datasources/
│           └── influxdb.yml    ← datasource preconfigurada
├── influxdb/
│   └── init/
│       └── create-buckets.sh  ← crea buckets en el primer arranque
├── docker-compose.yml
├── .env                        ← credenciales reales (NO commitear)
└── .env.example                ← plantilla
```

---

## Requisitos

- **Docker Desktop** (o Docker Engine en Linux)
- **Python 3.10+**

```bash
pip install pyserial influxdb-client
```

- **Hardware**: ESP32 TX en el coche + ESP32 RX en pits conectado por USB a la laptop

---

## Setup inicial

### 1. Credenciales

```bash
cp .env.example .env
```

Edita `.env`:

| Variable | Descripción |
|---|---|
| `INFLUX_TOKEN` | Token para InfluxDB (invéntalo, debe coincidir en todos los servicios) |
| `INFLUX_PASSWORD` | Password del admin de InfluxDB |
| `GF_PASSWORD` | Password del admin de Grafana |
| `INFLUX_ORG` | Nombre de la organización (ej. `MadRams`) |
| `INFLUX_BUCKET` | Bucket de datos live (default `Telemetry`) |
| `INFLUX_MEASUREMENT` | Nombre del measurement (ej. `minibaja`, `formula`) |
| `TEAM_NAME` | Tag del equipo en cada punto (ej. `MadRams`) |

### 2. Iniciar el stack

```bash
docker compose up -d
```

En el **primer arranque** el script `influxdb/init/create-buckets.sh` crea automáticamente los buckets `telemetry-live` y `telemetry-analisis`. No hace falta hacerlo a mano.

- InfluxDB → http://localhost:8086 (usuario: `admin`)
- Grafana  → http://localhost:3000 (usuario: `admin`)

Los dashboards aparecen cargados automáticamente desde `grafana/provisioning/dashboards/`.

### 3. Firmware

Flashea el firmware al ESP32 TX (coche) y al ESP32 RX (pits).  
Ver `firmware/README.md` para instrucciones completas de setup, arquitectura de tasks, y selección de SF/BW.

---

## Uso en carrera

### Receptor LoRa en vivo

Conecta el ESP32 RX al USB de la laptop y corre:

```bash
# Windows
python3 laptop/lora_receiver_local.py --port COM3 --run_id run_042 --test suspension_rocks

# Linux / Mac
python3 laptop/lora_receiver_local.py --port /dev/ttyUSB0 --run_id run_042 --test suspension_rocks
```

| Argumento | Descripción | Ejemplo |
|---|---|---|
| `--port` | Puerto serial del ESP32 RX | `COM3` / `/dev/ttyUSB0` |
| `--run_id` | Identificador de la corrida — se escribe como tag en InfluxDB | `run_042` |
| `--test` | Nombre del test o condición — se escribe como tag | `suspension_rocks` |
| `--baud` | Baudrate (default: 115200) | `9600` |

El receptor:
- Descarta líneas no-JSON (prints de debug del ESP32) y paquetes sin `rpm`/`temp`
- Asigna timestamps deterministas: `t_anchor + msg_id × 200 ms`
- Si arranca tarde, extrapola el anchor hacia atrás — la rejilla de tiempos es consistente desde el primer paquete
- Mantiene hasta 1000 puntos en RAM si InfluxDB no responde y los reenvía al reconectar
- Descarta duplicados exactos (mismo `msg_id` ya escrito en esta sesión)
- Solo escribe `lat`/`lng` cuando `gps_fix == 1`

### Ver datos en Grafana

Abre http://localhost:3000 y selecciona en los filtros superiores:

| Filtro | Qué poner |
|---|---|
| **Measurement** | El valor de `INFLUX_MEASUREMENT` en tu `.env` |
| **Run ID** | El `--run_id` con el que corriste el receptor |
| **Test** | El `--test` con el que corriste el receptor |

Dashboards disponibles:

| Dashboard | Bucket | Descripción |
|---|---|---|
| **Live Telemetry** | `telemetry-live` | Monitoreo en tiempo real durante la carrera |
| **Post-Race Analysis** | `telemetry-analisis` | Análisis post-carrera con datos a 10 Hz de SD card |

---

## Post-carrera: subir datos de SD card

El ESP32 TX escribe un CSV a 10 Hz en la SD card. Después de la carrera, copia el archivo y sube los datos para análisis de alta resolución:

```bash
python3 laptop/sd_upload.py --run_id run_042 --test suspension_rocks --csv /ruta/al/run_0042.csv
```

Formato esperado del CSV:

```
sample_idx,rpm,speed,temp,temp_cvt,vbat,suspension,throttle,lat,lng,gps_fix,lap
0,0.0,0.0,0.0,0.0,12.1,0.0,0.0,0.0,0.0,0,0
1,0.0,0.0,0.0,0.0,12.1,0.0,0.0,0.0,0.0,0,0
42,2100.0,35.0,82.0,75.0,12.4,-0.050,60.0,20.6736,-103.344,1,3
...
```

`sample_idx` corresponde al mismo `msg_id` del paquete LoRa — el ESP32 usa un solo contador para ambos.

### Cómo funciona el anchor de timestamps

El script necesita saber a qué timestamp de InfluxDB corresponde el `sample_idx=0` del CSV, para insertar los datos a 10 Hz en la misma rejilla temporal que los datos live.

1. Escanea hasta las primeras 100 filas buscando las que tienen sensores activos (descarta filas donde `rpm==0` y `temp==0` — sensores aún sin inicializar).
2. Por cada fila válida, busca en InfluxDB el punto live con el mismo `sample_idx` (si ese paquete fue transmitido por LoRa, tiene el mismo ID).
3. Calcula el anchor como `live_ts[K] - K × 200 ms` para cada par encontrado y toma la **mediana** (invariante matemático: siempre da el mismo valor).
4. Si los anchors difieren más de 500 ms entre sí, lanza una advertencia (posible mezcla de runs).
5. Aborta **solo** si no se encontró ninguna coincidencia entre CSV y datos live — lo que indica run/test incorrecto o que SD y LoRa no tienen overlap temporal.

Los datos se insertan en el bucket `telemetry-analisis` a 10 Hz (100 ms por fila).

### Dashboard Post-Race Analysis

- Panel **Overlay**: superpone datos LoRa (5 Hz) y SD card (10 Hz) del mismo run en el mismo eje temporal.
- Panel **Comparación multi-corrida**: una línea por `run_id`; selecciona varios para comparar condiciones.
- Panel **Estadísticas**: max, min y avg de cada campo para el run seleccionado.

---

## Simulador (sin hardware)

Para probar el stack completo sin tener el hardware conectado.

Requiere un par de puertos seriales virtuales:

**Windows** — instala [com0com](https://sourceforge.net/projects/com0com/) y crea el par COM10↔COM11.

**Linux:**
```bash
socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1
```

Luego en dos terminales:

```bash
# Terminal 1 — simulador (escribe en COM10 / /tmp/ttyV0)
python3 laptop/dataSimulator/lora_serial_sim.py --port COM10

# Terminal 2 — receptor (lee de COM11 / /tmp/ttyV1)
python3 laptop/lora_receiver_local.py --port COM11 --run_id sim_001 --test simulacion
```

Flags del simulador:

| Flag | Descripción | Default |
|---|---|---|
| `--port` | Puerto serial de escritura | requerido |
| `--lat` | Latitud central de la pista | Mónaco |
| `--lng` | Longitud central de la pista | Mónaco |
| `--rate` | Hz de envío | 2 |
| `--noise` | Añade líneas de debug tipo ESP32 | off |

El simulador replica el mismo esquema JSON y modelo físico que el ESP32 real, por lo que es un sustituto fiel para pruebas de integración.

---

## Detener el stack

```bash
docker compose down
```

Los datos **persisten** en volúmenes Docker. Para borrar todo:

```bash
docker compose down -v   # ⚠️ elimina todos los datos de InfluxDB y Grafana
```

---

## Troubleshooting

**Los paneles de Grafana están vacíos**
- Verifica que `INFLUX_MEASUREMENT` en `.env` coincida con el filtro **Measurement** en Grafana.
- Confirma que `--run_id` y `--test` son exactamente los mismos en el receptor y en los filtros de Grafana.

**`lora_receiver_local.py` no conecta a serial**
- En Windows: verifica el número de COM en el Administrador de dispositivos.
- En Linux: puede que necesites `sudo usermod -aG dialout $USER` y volver a iniciar sesión.

**InfluxDB no acepta escrituras**
- Verifica que `INFLUX_TOKEN` en `.env` coincida con el token en `grafana/provisioning/datasources/influxdb.yml`.
- El receptor tiene un buffer de 1000 puntos en RAM; los datos no se pierden mientras InfluxDB vuelve.

**`sd_upload.py` aborta sin encontrar coincidencias**
- Verifica que `--run_id` y `--test` sean los mismos con los que corrió `lora_receiver_local.py` durante la carrera.
- Confirma que hay datos live en InfluxDB para ese run (abre Grafana y filtra por ese run_id).
- Si el receptor no estaba corriendo al mismo tiempo que el ESP32 TX grababa en SD, no hay overlap y el anchor no se puede calcular.

---

## Notas de arquitectura

**Timestamps deterministas** — el receptor no usa el tiempo de llegada del paquete, sino `t_anchor + msg_id × 200 ms`. Esto elimina el jitter de radio: si un paquete llega tarde, se inserta retroactivamente en InfluxDB con su timestamp correcto. El anchor se establece con el primer paquete recibido y se extrapola hacia atrás si el receptor arrancó después del ESP32.

**Dual SPI en el transmisor** — LoRa usa VSPI y la SD card usa HSPI. Los buses son independientes, así que `taskLoRaSend` y `taskSDWrite` pueden correr sin mutex entre ellos. Ver `firmware/README.md` para el detalle de pines.

**Descarte de duplicados** — si un paquete llega dos veces (retransmisión de radio), el receptor detecta el `msg_id` duplicado y descarta la segunda copia sin escribirla a InfluxDB.

**Buffer offline** — `InfluxWriter` mantiene un `deque` con hasta 1000 puntos en RAM. Si InfluxDB no responde (reinicio de Docker, etc.), los puntos se acumulan y se reenvían automáticamente al reconectar. No se pierde data mientras el buffer no se llene.
