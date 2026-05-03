# Laptop — Scripts de Pits

Código que corre en la laptop de pits durante y después de la carrera.

| Script | Cuándo usarlo | Descripción |
|---|---|---|
| `lora_receiver_local.py` | Durante la carrera | Lee JSON del ESP32 RX por serial y escribe a InfluxDB en tiempo real |
| `sd_upload.py` | Post-carrera | Sube el CSV de la SD card a InfluxDB para análisis de alta resolución |
| `dataSimulator/lora_serial_sim.py` | Pruebas sin hardware | Simula el ESP32 TX escribiendo JSON por serial virtual |

Las credenciales se leen automáticamente de `localDashboard/.env`.

---

## lora_receiver_local.py

```bash
python3 lora_receiver_local.py --port COM3 --run_id run_042 --test suspension_rocks
python3 lora_receiver_local.py --port /dev/ttyUSB0 --run_id run_042 --test suspension_rocks
```

| Argumento | Requerido | Descripción |
|---|---|---|
| `--port` | sí | Puerto serial del ESP32 RX |
| `--run_id` | sí | ID de la corrida (tag en InfluxDB) |
| `--test` | sí | Nombre del test (tag en InfluxDB) |
| `--baud` | no | Baudrate (default: 115200) |

Escribe al bucket `telemetry-live` a 5 Hz. Descarta líneas no-JSON y paquetes sin `rpm`/`temp`. Mantiene buffer de 1000 puntos en RAM si InfluxDB no responde.

---

## sd_upload.py

```bash
python3 sd_upload.py --run_id run_042 --test suspension_rocks --csv /ruta/datos.csv
```

| Argumento | Requerido | Descripción |
|---|---|---|
| `--run_id` | sí | Debe coincidir con el `--run_id` del receptor que corrió durante esa sesión |
| `--test` | sí | Debe coincidir con el `--test` del receptor |
| `--csv` | sí | Ruta al archivo CSV de la SD card |

Escribe al bucket `telemetry-analisis` a 10 Hz. Requiere que `lora_receiver_local.py` haya corrido durante la misma sesión para poder anclar los timestamps.

---

## dataSimulator/lora_serial_sim.py

Requiere par de puertos virtuales (com0com en Windows, socat en Linux).

```bash
# Terminal 1 — simulador
python3 dataSimulator/lora_serial_sim.py --port COM10

# Terminal 2 — receptor
python3 lora_receiver_local.py --port COM11 --run_id sim_001 --test simulacion
```

| Flag | Descripción | Default |
|---|---|---|
| `--port` | Puerto de escritura | requerido |
| `--lat` | Latitud central de la pista | Mónaco |
| `--lng` | Longitud central de la pista | Mónaco |
| `--rate` | Hz de envío | 2 |
| `--noise` | Añade líneas de debug tipo ESP32 | off |

---

Ver `localDashboard/README.md` para el flujo completo, arquitectura de timestamps y troubleshooting.
