# Live Firmware — ESP32 Transmitter

El ESP32 del vehículo se conecta directamente al hotspot del celular y escribe a InfluxDB Cloud via HTTPS. No se necesita receptor ESP32 ni laptop en pits.

```
ESP32 (coche) ──WiFi──► Hotspot (celular) ──Internet──► InfluxDB Cloud ──► Grafana Cloud
```

## Setup

1. Instala Arduino IDE con el core de ESP32 (mismo que para `localDashboard/firmware/`).

2. Instala las siguientes librerías via Library Manager:
   - **ESP32 InfluxDB** (by Tobias Kopecek) — cliente HTTPS para InfluxDB Cloud
   - **TinyGPSPlus** (by Mikal Hart)

3. Copia y llena `config.h`:
   ```
   cd liveDashboard/firmware/transmitter
   cp config.h.example config.h
   # Edita config.h: WIFI_SSID, WIFI_PASSWORD, INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
   ```

4. Abre `transmitter.ino` en Arduino IDE y flashea al ESP32.

## Diferencias con el stack local

| Aspecto | Local | Live |
|---|---|---|
| Conectividad | LoRa 915 MHz | WiFi → hotspot celular |
| ESP32s | 2 (TX en coche + RX en pits) | 1 (solo TX en coche) |
| Laptop necesaria | Sí (corre `lora_receiver_local.py`) | No |
| Internet | No (todo local en Docker) | Sí (InfluxDB Cloud) |
| SD card | Sí (respaldo a 10 Hz) | No |
| Timestamps | Deterministas por `msg_id` | Wall-clock via NTP |

## config.h

| Campo | Descripción |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | Red WiFi del hotspot del celular |
| `INFLUX_URL` | URL de tu instancia InfluxDB Cloud |
| `INFLUX_TOKEN` | Token de escritura de InfluxDB Cloud |
| `INFLUX_ORG` / `INFLUX_BUCKET` | Organización y bucket en InfluxDB Cloud |
| `INFLUX_MEASUREMENT` | Nombre del measurement (debe coincidir con el filtro en Grafana) |
| `TEAM_NAME` | Tag de equipo en cada punto |
| `TZ_INFO` | Timezone POSIX para sincronización NTP |
| Pines de sensores | Mismos que `localDashboard/firmware/` |
