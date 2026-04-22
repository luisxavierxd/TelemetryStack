#!/usr/bin/env python3
"""
Minibaja SAE — Receptor LoRa Serial → InfluxDB local
Lee paquetes del receptor LoRa por puerto serial y escribe a InfluxDB local (Docker).

El ESP32 receptor envía JSON por serial USB:
{"rpm":2100,"speed":35,"temp":82,"temp_cvt":75,"vbat":12.4,
 "suspension":-0.05,"lat":20.6736,"lng":-103.344,
 "gps_fix":1,"lap":3,"flags":0}

Usage:
    pip install pyserial influxdb-client
    python3 lora_receiver_local.py --port /dev/ttyUSB0     # Linux
    python3 lora_receiver_local.py --port COM3              # Windows
    python3 lora_receiver_local.py --port /dev/tty.usbserial-0001  # Mac
"""

import json, time, argparse, sys, os
from collections import deque
from pathlib import Path

# Cargar .env si existe (para INFLUX_TOKEN)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

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

# ─── Config InfluxDB local (coincide con docker-compose.yml) ─────────────────
INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG    = "MadRams"
INFLUX_BUCKET = "Telemetry"

MAX_BUFFER    = 1000   # puntos en RAM si InfluxDB no responde


# ─── InfluxWriter con autoreconnect (igual que en simulador) ──────────────────
class InfluxWriter:
    def __init__(self, url, token, org, bucket, max_buffer=MAX_BUFFER):
        self.url        = url
        self.token      = token
        self.org        = org
        self.bucket     = bucket
        self._buffer    = deque(maxlen=max_buffer)
        self._connected = False
        self._client    = None
        self._write_api = None
        self._retry_at  = 0.0
        self.RETRY_INTERVAL = 5
        self._connect()

    def _connect(self):
        try:
            if self._client:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client    = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._client.ping()
            self._connected = True
            print(f"  [influx] conectado OK → {self.url}")
        except Exception as e:
            print(f"  [influx] conexión fallida: {e}")
            print(f"  [influx] ¿está corriendo docker-compose up?")
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
    def buffer_size(self):
        return len(self._buffer)

    @property
    def is_connected(self):
        return self._connected


# ─── Parseo del paquete JSON del ESP32 ───────────────────────────────────────
def parse_packet(line: str) -> Point | None:
    """
    Convierte la línea JSON del serial en un Point de InfluxDB.
    Retorna None si la línea no es JSON válido o faltan campos.
    """
    try:
        d = json.loads(line.strip())
    except json.JSONDecodeError:
        return None   # línea de debug del ESP32, ignorar

    # Campos mínimos requeridos
    if "rpm" not in d or "temp" not in d:
        return None

    p = (Point("minibaja")
        .tag("device", "vehicle")
        .tag("team",   "MadRams")
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

    # GPS solo si tiene fix válido
    if d.get("gps_fix") and d.get("lat") and d.get("lng"):
        p = p.field("lat", float(d["lat"]))
        p = p.field("lng", float(d["lng"]))

    return p


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Receptor LoRa Serial → InfluxDB local")
    parser.add_argument("--port",    required=True,
                        help="Puerto serial, ej: /dev/ttyUSB0 o COM3")
    parser.add_argument("--baud",    type=int, default=115200,
                        help="Baudrate del receptor LoRa (default: 115200)")
    parser.add_argument("--influx-url",   default=INFLUX_URL)
    parser.add_argument("--influx-token", default=INFLUX_TOKEN)
    parser.add_argument("--influx-org",   default=INFLUX_ORG)
    parser.add_argument("--influx-bucket",default=INFLUX_BUCKET)
    args = parser.parse_args()

    # ── Serial ────────────────────────────────────────────────────────────────
    print(f"Abriendo puerto serial {args.port} a {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2)
        print(f"  [serial] OK")
    except Exception as e:
        print(f"  [serial] ERROR: {e}")
        sys.exit(1)

    # ── InfluxDB ──────────────────────────────────────────────────────────────
    influx = InfluxWriter(
        url=args.influx_url,
        token=args.influx_token,
        org=args.influx_org,
        bucket=args.influx_bucket,
    )

    print(f"\nEscuchando paquetes LoRa — Ctrl+C para detener")
    print("-" * 60)

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
                # Línea de debug del ESP32 — imprimir para diagnóstico
                debug = raw.strip()
                if debug:
                    print(f"  [esp32] {debug}")
                err_count += 1
                continue

            influx.write(point)
            pkt_count += 1

            # Print resumen cada 5 segundos
            now = time.time()
            if now - last_print >= 5:
                last_print = now
                try:
                    d = json.loads(raw.strip())
                    buf = f"  BUF:{influx.buffer_size}" if influx.buffer_size > 0 else ""
                    cx  = "INFLUX:OK" if influx.is_connected else "INFLUX:OFF"
                    gx  = "GPS:OK" if d.get("gps_fix") else "GPS:NO"
                    print(
                        f"[pkts:{pkt_count}] "
                        f"RPM:{d.get('rpm',0):4.0f}  "
                        f"Speed:{d.get('speed',0):5.1f}km/h  "
                        f"Temp:{d.get('temp',0):5.1f}°C  "
                        f"Vbat:{d.get('vbat',0):.2f}V  "
                        f"Lap:{d.get('lap',0)}  "
                        f"{cx}  {gx}{buf}"
                    )
                except Exception:
                    print(f"  [pkts:{pkt_count}] errores:{err_count}")

    except KeyboardInterrupt:
        print(f"\nDetenido. Paquetes recibidos: {pkt_count} | Errores: {err_count} | Buffer: {influx.buffer_size} pts")
        ser.close()
        influx.close()


if __name__ == "__main__":
    main()