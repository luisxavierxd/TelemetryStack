"""
Minibaja SAE — Simulador Live (InfluxDB Cloud + HiveMQ MQTT)
Emula el vehículo y publica datos a la nube para pruebas sin hardware.

Por defecto manda a ambos destinos. Usa --target para seleccionar:
    --target influx   Solo InfluxDB Cloud
    --target mqtt     Solo HiveMQ MQTT
    --target both     Ambos (default)

Las credenciales se leen del .env en liveDashboard/ (directorio padre).
Pueden sobreescribirse con flags CLI.

Usage:
    pip install paho-mqtt influxdb-client python-dotenv requests
    python3 simulator.py                          # usa .env del padre
    python3 simulator.py --target influx          # solo InfluxDB
    python3 simulator.py --target mqtt            # solo MQTT
    python3 simulator.py --rate 5                 # 5 Hz
    python3 simulator.py --influx-token TOKEN     # override .env
"""

import json, time, math, random, argparse, ssl, sys, requests
from collections import deque
from pathlib import Path

# ─── Cargar .env del directorio padre (liveDashboard/) ───────────────────────
try:
    from dotenv import load_dotenv
    import os
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
except ImportError:
    print("  [warn] python-dotenv no instalado — pip install python-dotenv")
    import os

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Install: pip install paho-mqtt")
    sys.exit(1)

try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:
    print("Install: pip install influxdb-client")
    sys.exit(1)

# ─── Pista ────────────────────────────────────────────────────────────────────
TRACK_CENTER_LAT = 20.6736
TRACK_CENTER_LNG = -103.3440
TRACK_RADIUS_DEG = 0.002
MAX_BUFFER       = 500


# ─── InfluxDB con autoreconnect y buffer ──────────────────────────────────────
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
                print(f"  [influx] buffer vaciado: {len(pending)} pts")
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


# ─── Weather fetcher (Open-Meteo, sin API key) ────────────────────────────────
class WeatherFetcher:
    def __init__(self, interval: int = 60):
        self.interval    = interval
        self._last_fetch = 0.0
        self._cache: dict = {}

    def fetch(self, lat: float, lng: float) -> dict:
        now = time.time()
        if now - self._last_fetch < self.interval and self._cache:
            return self._cache
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lng,
                    "current": ",".join([
                        "temperature_2m", "relative_humidity_2m",
                        "wind_speed_10m", "wind_direction_10m",
                        "precipitation", "weather_code", "surface_pressure",
                    ]),
                    "wind_speed_unit": "kmh",
                },
                timeout=6,
            )
            r.raise_for_status()
            c = r.json()["current"]
            self._cache = {
                "air_temp":     float(c["temperature_2m"]),
                "humidity":     float(c["relative_humidity_2m"]),
                "wind_speed":   float(c["wind_speed_10m"]),
                "wind_dir":     float(c["wind_direction_10m"]),
                "rain":         float(c["precipitation"]),
                "pressure":     float(c["surface_pressure"]),
                "weather_code": int(c["weather_code"]),
            }
            self._last_fetch = now
            print(f"  [weather] {self._cache['air_temp']}°C  "
                  f"viento {self._cache['wind_speed']} km/h  "
                  f"lluvia {self._cache['rain']} mm")
        except Exception as e:
            print(f"  [weather] fetch failed: {e} — usando caché")
        return self._cache

    def to_influx_point(self, lat: float, lng: float) -> Point | None:
        data = self.fetch(lat, lng)
        if not data:
            return None
        return (Point("weather")
            .tag("source", "open-meteo")
            .tag("team",   "MadRams")
            .field("air_temp",     data["air_temp"])
            .field("humidity",     data["humidity"])
            .field("wind_speed",   data["wind_speed"])
            .field("wind_dir",     data["wind_dir"])
            .field("rain",         data["rain"])
            .field("pressure",     data["pressure"])
            .field("weather_code", float(data["weather_code"]))
        )


# ─── Simulador del vehículo ───────────────────────────────────────────────────
class MinibajaSim:
    def __init__(self):
        self.rpm               = 0.0
        self.speed             = 0.0
        self.suspension_height = 0.0
        self.temp_engine       = 25.0
        self.temp_cvt          = 30.0
        self.vbat              = 12.6
        self.angle             = 0.0
        self.throttle          = 0.0
        self.phase             = "idle"
        self.phase_timer       = 0.0
        self.msg_count         = 0
        self.lap_count         = 0
        self._prev_angle       = 0.0

    def update(self, dt: float = 0.1):
        self.phase_timer -= dt
        if self.phase_timer <= 0:
            self.phase       = random.choice(["accel", "cruise", "brake", "idle"])
            self.phase_timer = random.uniform(2, 8)

        targets = {"accel": 0.9, "cruise": 0.55, "brake": 0.0, "idle": 0.05}
        self.throttle += (targets[self.phase] - self.throttle) * 0.12

        self.rpm += (self.throttle * 3800 + random.gauss(0, 25) - self.rpm) * 0.15
        self.rpm  = max(0.0, self.rpm)

        target_speed = (
            min(1.0, max(0, (self.rpm - 1800) / 1500)) * 45
            if self.rpm > 1800 else 0
        )
        self.speed += (target_speed - self.speed) * 0.08 - 0.02 * self.speed * dt
        self.speed  = max(0.0, self.speed)

        self.suspension_height += random.gauss(0, 0.02) - self.suspension_height * 0.1 * dt

        rpm_ratio        = self.rpm / 3800
        self.temp_engine += ((rpm_ratio * 2.2) - (self.temp_engine - 25) * 0.012) * dt + random.gauss(0, 0.1)
        self.temp_cvt    += ((rpm_ratio * 1.5) - (self.temp_cvt    - 28) * 0.008) * dt + random.gauss(0, 0.08)
        self.vbat         = 12.6 - rpm_ratio * 0.8 + random.gauss(0, 0.02)

        self._prev_angle = self.angle
        self.angle      += (self.speed / 3.6) / (TRACK_RADIUS_DEG * 111_000) * dt
        if self._prev_angle % (2 * math.pi) > self.angle % (2 * math.pi):
            self.lap_count += 1

        self.msg_count += 1

    @property
    def lat(self) -> float:
        return round(TRACK_CENTER_LAT + TRACK_RADIUS_DEG * math.cos(self.angle), 6)

    @property
    def lng(self) -> float:
        return round(TRACK_CENTER_LNG + TRACK_RADIUS_DEG * math.sin(self.angle), 6)

    def to_dict(self) -> dict:
        return {
            "ts":         int(time.time() * 1000),
            "rpm":        round(self.rpm),
            "speed":      round(self.speed, 1),
            "temp":       round(self.temp_engine, 1),
            "temp_cvt":   round(self.temp_cvt, 1),
            "vbat":       round(self.vbat, 2),
            "suspension": round(self.suspension_height, 3),
            "throttle":   round(self.throttle * 100),
            "lat":        self.lat,
            "lng":        self.lng,
            "gps_fix":    1,
            "phase":      self.phase,
            "lap":        self.lap_count,
        }

    def to_influx_point(self) -> Point:
        return (Point("minibaja")
            .tag("device", "simulator")
            .tag("team",   "MadRams")
            .field("rpm",        float(round(self.rpm)))
            .field("speed",      float(round(self.speed, 1)))
            .field("temp",       float(round(self.temp_engine, 1)))
            .field("temp_cvt",   float(round(self.temp_cvt, 1)))
            .field("vbat",       float(round(self.vbat, 2)))
            .field("suspension", float(round(self.suspension_height, 3)))
            .field("throttle",   float(round(self.throttle * 100)))
            .field("lat",        float(self.lat))
            .field("lng",        float(self.lng))
            .field("gps_fix",    1.0)
            .field("lap",        float(self.lap_count))
        )


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Minibaja Live Simulator — InfluxDB Cloud + HiveMQ")

    # Target
    p.add_argument("--target", choices=["influx", "mqtt", "both"], default="both",
                   help="Destino de los datos (default: both)")

    # InfluxDB — default desde .env
    p.add_argument("--influx-url",    default=os.getenv("INFLUX_URL"))
    p.add_argument("--influx-token",  default=os.getenv("INFLUX_TOKEN"))
    p.add_argument("--influx-org",    default=os.getenv("INFLUX_ORG"))
    p.add_argument("--influx-bucket", default=os.getenv("INFLUX_BUCKET", "Telemetry"))

    # MQTT — default desde .env
    p.add_argument("--mqtt-host",  default=os.getenv("MQTT_HOST"))
    p.add_argument("--mqtt-port",  type=int, default=int(os.getenv("MQTT_PORT", 8883)))
    p.add_argument("--mqtt-user",  default=os.getenv("MQTT_USER"))
    p.add_argument("--mqtt-pass",  default=os.getenv("MQTT_PASS"))

    # Sim
    p.add_argument("--rate",             type=float, default=10,
                   help="Hz de publicación (default: 10)")
    p.add_argument("--weather-interval", type=int,   default=60,
                   help="Segundos entre fetch de Open-Meteo (default: 60)")
    p.add_argument("--buffer-size",      type=int,   default=MAX_BUFFER)

    args = p.parse_args()

    use_influx = args.target in ("influx", "both")
    use_mqtt   = args.target in ("mqtt",   "both")

    # ── Validar credenciales requeridas ───────────────────────────────────────
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

    interval = 1.0 / args.rate

    # ── MQTT ──────────────────────────────────────────────────────────────────
    mqtt_client = None
    if use_mqtt:
        mqtt_client = mqtt.Client(client_id="sim-minibaja-live", protocol=mqtt.MQTTv311)
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
            max_buffer=args.buffer_size,
        )

    # ── Sim + Weather ─────────────────────────────────────────────────────────
    sim             = MinibajaSim()
    weather         = WeatherFetcher(interval=args.weather_interval)
    weather_counter = 0.0

    targets_str = args.target.upper()
    print(f"\nSimulando a {args.rate} Hz → {targets_str} — Ctrl+C para detener")
    print("-" * 65)

    try:
        while True:
            sim.update(interval)

            if use_mqtt and mqtt_client:
                mqtt_client.publish("minibaja/telemetry", json.dumps(sim.to_dict()))

            if use_influx and influx:
                influx.write(sim.to_influx_point())

                weather_counter += interval
                if weather_counter >= args.weather_interval:
                    weather_counter = 0.0
                    wp = weather.to_influx_point(sim.lat, sim.lng)
                    if wp:
                        influx.write(wp)

            # Print cada segundo
            if sim.msg_count % int(args.rate) == 0:
                d   = sim.to_dict()
                buf = f"  BUF:{influx.buffer_size}" if (influx and influx.buffer_size > 0) else ""
                cx  = f"INFLUX:{'OK' if influx and influx.is_connected else 'OFF'}" if use_influx else ""
                mx  = "MQTT:ON" if use_mqtt else ""
                print(
                    f"[{d['phase']:6s}] "
                    f"RPM:{d['rpm']:4d}  "
                    f"Speed:{d['speed']:5.1f}km/h  "
                    f"Temp:{d['temp']:5.1f}°C  "
                    f"CVT:{d['temp_cvt']:5.1f}°C  "
                    f"Vbat:{d['vbat']:.2f}V  "
                    f"Lap:{d['lap']}  "
                    f"{cx}  {mx}{buf}"
                )

            time.sleep(interval)

    except KeyboardInterrupt:
        buf = influx.buffer_size if influx else 0
        print(f"\nDetenido. {sim.msg_count} msgs | Buffer pendiente: {buf} pts")
        if mqtt_client:
            mqtt_client.disconnect()
        if influx:
            influx.close()


if __name__ == "__main__":
    main()