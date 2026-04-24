"""
Minibaja SAE — Receptor LoRa Serial → InfluxDB Cloud + HiveMQ MQTT
Lee paquetes del receptor LoRa por puerto serial y publica a la nube.

El ESP32 receptor envía JSON por serial USB:
{"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,
 "gps_fix":1,"lap":3,"flags":0}

Las credenciales se leen del .env en liveDashboard/ (directorio actual).
Pueden sobreescribirse con flags CLI.

Usage:
    pip install pyserial influxdb-client paho-mqtt python-dotenv
    python3 lora_receiver_live.py --port COM3
    python3 lora_receiver_live.py --port /dev/ttyUSB0 --target influx
    python3 lora_receiver_live.py --port COM3 --target mqtt
    python3 lora_receiver_live.py --port COM3 --target both
"""

import json, time, argparse, sys, ssl
from collections import deque
from pathlib import Path

# ─── Cargar .env del directorio actual (liveDashboard/) ──────────────────────
try:
    from dotenv import load_dotenv
    import os
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except ImportError:
    print("  [warn] python-dotenv no instalado — pip install python-dotenv")
    import os

TEAM_NAME = os.getenv("TEAM_NAME", "equipo")

try:
    import serial
except ImportError:
    print("Install: pip install pyserial")
    sys.exit(1)

try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:
    print("Install: pip install influxdb-client")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Install: pip install paho-mqtt")
    sys.exit(1)


# ─── InfluxDB con autoreconnect y buffer ──────────────────────────────────────
class InfluxWriter:
    def __init__(self, url, token, org, bucket, max_buffer=1000):
        self.url        = url
        self.token      = token
        self.org        = org
        self.bucket     = bucket
        self._buffer    = deque(maxlen=max_buffer)
        self._connected = False
        self._client    = None
        self._write_api = None
        self._retry_at  = 0.0
        self.RETRY_INTERVAL = 10
        self._connect()

    def _connect(self):
        try:
            if self._client:
                try: self._client.close()
                except: pass
            self._client    = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._client.ping()
            self._connected = True
            print(f"  [influx] conectado OK → {self.url}")
        except Exception as e:
            print(f"  [influx] conexión fallida: {e}")
            self._connected = False

    def write(self, point: Point):
        now = time.time()
        if not self._connected:
            if now >= self._retry_at:
                print(f"  [influx] reintentando... (buffer: {len(self._buffer)} pts)")
                self._connect()
                self._retry_at = now + self.RETRY_INTERVAL
            if not self._connected:
                self._buffer.append(point)
                return

        if self._buffer:
            pending = list(self._buffer)
            self._buffer.clear()
            try:
                self._write_api.write(bucket=self.bucket, record=pending)
                print(f"  [influx] buffer vaciado: {len(pending)} pts reenviados")
            except Exception as e:
                print(f"  [influx] error vaciando buffer: {e}")
                self._buffer.extend(pending)
                self._connected = False
                self._retry_at  = now + self.RETRY_INTERVAL
                self._buffer.append(point)
                return

        try:
            self._write_api.write(bucket=self.bucket, record=point)
        except Exception as e:
            print(f"  [influx] write error: {e}")
            self._connected = False
            self._retry_at  = now + self.RETRY_INTERVAL
            self._buffer.append(point)

    def close(self):
        if self._client:
            self._client.close()

    @property
    def buffer_size(self): return len(self._buffer)

    @property
    def is_connected(self): return self._connected


# ─── Parseo del paquete JSON del ESP32 ───────────────────────────────────────
def parse_packet(line: str) -> Point | None:
    try:
        d = json.loads(line.strip())
    except json.JSONDecodeError:
        return None

    if "rpm" not in d or "temp" not in d:
        return None

    p = (Point("minibaja")
        .tag("device", "vehicle")
        .tag("team",   TEAM_NAME)
        .field("rpm",        float(d.get("rpm",        0)))
        .field("speed",      float(d.get("speed",      0)))
        .field("temp",       float(d.get("temp",       0)))
        .field("temp_cvt",   float(d.get("temp_cvt",   0)))
        .field("vbat",       float(d.get("vbat",      12.0)))
        .field("suspension", float(d.get("suspension", 0)))
        .field("throttle",   float(d.get("throttle",   0)))
        .field("lap",        float(d.get("lap",        0)))
        .field("gps_fix",    float(d.get("gps_fix",    0)))
    )

    if d.get("gps_fix") and d.get("lat") and d.get("lng"):
        p = p.field("lat", float(d["lat"]))
        p = p.field("lng", float(d["lng"]))

    return p


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Receptor LoRa Serial → InfluxDB Cloud + HiveMQ")

    parser.add_argument("--port", required=True,
                        help="Puerto serial, ej: /dev/ttyUSB0 o COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--target", choices=["influx", "mqtt", "both"], default="both",
                        help="Destino de los datos (default: both)")

    # InfluxDB — default desde .env
    parser.add_argument("--influx-url",    default=os.getenv("INFLUX_URL"))
    parser.add_argument("--influx-token",  default=os.getenv("INFLUX_TOKEN"))
    parser.add_argument("--influx-org",    default=os.getenv("INFLUX_ORG"))
    parser.add_argument("--influx-bucket", default=os.getenv("INFLUX_BUCKET", "Telemetry"))

    # MQTT — default desde .env
    parser.add_argument("--mqtt-host",  default=os.getenv("MQTT_HOST"))
    parser.add_argument("--mqtt-port",  type=int, default=int(os.getenv("MQTT_PORT", 8883)))
    parser.add_argument("--mqtt-user",  default=os.getenv("MQTT_USER"))
    parser.add_argument("--mqtt-pass",  default=os.getenv("MQTT_PASS"))

    args = parser.parse_args()

    use_influx = args.target in ("influx", "both")
    use_mqtt   = args.target in ("mqtt",   "both")

    # ── Validar credenciales ──────────────────────────────────────────────────
    if use_influx:
        missing = [k for k, v in {
            "--influx-url":   args.influx_url,
            "--influx-token": args.influx_token,
            "--influx-org":   args.influx_org,
        }.items() if not v]
        if missing:
            print(f"[ERROR] Faltan credenciales InfluxDB: {', '.join(missing)}")
            print("        Define en liveDashboard/.env o pasa como flags CLI")
            sys.exit(1)

    if use_mqtt:
        missing = [k for k, v in {
            "--mqtt-host": args.mqtt_host,
            "--mqtt-user": args.mqtt_user,
            "--mqtt-pass": args.mqtt_pass,
        }.items() if not v]
        if missing:
            print(f"[ERROR] Faltan credenciales MQTT: {', '.join(missing)}")
            print("        Define en liveDashboard/.env o pasa como flags CLI")
            sys.exit(1)

    # ── Serial ────────────────────────────────────────────────────────────────
    print(f"Abriendo puerto serial {args.port} a {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2)
        print(f"  [serial] OK")
    except Exception as e:
        print(f"  [serial] ERROR: {e}")
        sys.exit(1)

    # ── MQTT ──────────────────────────────────────────────────────────────────
    mqtt_client = None
    if use_mqtt:
        mqtt_client = mqtt.Client(client_id="lora-receiver-live", protocol=mqtt.MQTTv311)
        mqtt_client.username_pw_set(args.mqtt_user, args.mqtt_pass)
        mqtt_client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
        mqtt_client.on_connect    = lambda c, u, f, rc: print(
            f"  [mqtt] {'conectado OK' if rc == 0 else f'ERROR rc={rc}'}"
        )
        mqtt_client.on_disconnect = lambda c, u, rc: print(
            f"  [mqtt] desconectado (rc={rc}) — reconectando..."
        )
        print(f"Conectando MQTT → {args.mqtt_host}:{args.mqtt_port} ...")
        mqtt_client.connect(args.mqtt_host, args.mqtt_port, keepalive=60)
        mqtt_client.loop_start()

    # ── InfluxDB ──────────────────────────────────────────────────────────────
    influx = None
    if use_influx:
        print(f"Conectando InfluxDB → {args.influx_url} ...")
        influx = InfluxWriter(
            url=args.influx_url,
            token=args.influx_token,
            org=args.influx_org,
            bucket=args.influx_bucket,
        )

    targets_str = args.target.upper()
    print(f"\nEscuchando paquetes LoRa → {targets_str} — Ctrl+C para detener")
    print("-" * 65)

    pkt_count  = 0
    err_count  = 0
    last_print = time.time()

    try:
        while True:
            try:
                raw = ser.readline().decode("utf-8", errors="replace")
            except Exception as e:
                print(f"  [serial] error lectura: {e}")
                time.sleep(1)
                continue

            if not raw.strip():
                continue

            point = parse_packet(raw)

            if point is None:
                debug = raw.strip()
                if debug:
                    print(f"  [esp32] {debug}")
                err_count += 1
                continue

            # Publicar a los destinos activos
            if use_influx and influx:
                influx.write(point)

            if use_mqtt and mqtt_client:
                try:
                    d = json.loads(raw.strip())
                    d["ts"] = int(time.time() * 1000)
                    mqtt_client.publish("minibaja/telemetry", json.dumps(d))
                except Exception as e:
                    print(f"  [mqtt] publish error: {e}")

            pkt_count += 1

            # Print resumen cada 5 segundos
            now = time.time()
            if now - last_print >= 5:
                last_print = now
                try:
                    d   = json.loads(raw.strip())
                    buf = f"  BUF:{influx.buffer_size}" if (influx and influx.buffer_size > 0) else ""
                    cx  = f"INFLUX:{'OK' if influx and influx.is_connected else 'OFF'}" if use_influx else ""
                    mx  = "MQTT:ON" if use_mqtt else ""
                    gx  = "GPS:OK" if d.get("gps_fix") else "GPS:NO"
                    print(
                        f"[pkts:{pkt_count}] "
                        f"RPM:{d.get('rpm',0):4.0f}  "
                        f"Speed:{d.get('speed',0):5.1f}km/h  "
                        f"Temp:{d.get('temp',0):5.1f}°C  "
                        f"Vbat:{d.get('vbat',0):.2f}V  "
                        f"Lap:{d.get('lap',0)}  "
                        f"{cx}  {mx}  {gx}{buf}"
                    )
                except Exception:
                    print(f"  [pkts:{pkt_count}] errores:{err_count}")

    except KeyboardInterrupt:
        buf = influx.buffer_size if influx else 0
        print(f"\nDetenido. Paquetes: {pkt_count} | Errores: {err_count} | Buffer: {buf} pts")
        ser.close()
        if mqtt_client:
            mqtt_client.disconnect()
        if influx:
            influx.close()


if __name__ == "__main__":
    main()