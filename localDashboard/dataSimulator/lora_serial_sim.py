#!/usr/bin/env python3
"""
Minibaja SAE — Simulador ESP32 LoRa via Serial Virtual
Emula exactamente lo que enviaría el ESP32 receptor por USB serial.
Escribe JSON por un puerto COM virtual — el lora_receiver.py lee del otro extremo.

Setup Windows (com0com):
    1. Instala com0com: https://sourceforge.net/projects/com0com/
    2. Crea par virtual: COM10 <-> COM11
    3. Corre este script con --port COM10
    4. Corre lora_receiver.py con --port COM11

Setup Linux (socat):
    socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1
    python3 lora_serial_sim.py --port /tmp/ttyV0
    python3 lora_receiver.py --port /tmp/ttyV1

Usage:
    pip install pyserial
    python3 lora_serial_sim.py --port COM10
    python3 lora_serial_sim.py --port COM10 --rate 2
"""

import json, time, math, random, argparse, sys

try:
    import serial
except ImportError:
    print("Install: pip install pyserial")
    sys.exit(1)

# ─── Pista ────────────────────────────────────────────────────────────────────
TRACK_CENTER_LAT = 20.6736
TRACK_CENTER_LNG = -103.3440
TRACK_RADIUS_DEG = 0.002


# ─── Simulador del vehículo (misma lógica que simulator.py) ──────────────────
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

    def update(self, dt: float = 0.5):
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

        self.vbat = 12.6 - rpm_ratio * 0.8 + random.gauss(0, 0.02)

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

    def to_lora_dict(self) -> dict:
        """
        Formato exacto que enviaría el ESP32 por serial.
        Campos mínimos que espera lora_receiver.py
        """
        return {
            "rpm":        round(self.rpm),
            "speed":      round(self.speed, 1),
            "temp":       round(self.temp_engine, 1),
            "temp_cvt":   round(self.temp_cvt, 1),
            "vbat":       round(self.vbat, 2),
            "suspension": round(self.suspension_height, 3),
            "lat":        self.lat,
            "lng":        self.lng,
            "gps_fix":    1,
            "lap":        self.lap_count,
            "throttle":   round(self.throttle * 100),
        }


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Simulador ESP32 LoRa → Serial virtual")
    p.add_argument("--port", required=True,
                   help="Puerto serial virtual de escritura, ej: COM10 o /tmp/ttyV0")
    p.add_argument("--baud", type=int, default=115200,
                   help="Baudrate (debe coincidir con lora_receiver.py, default: 115200)")
    p.add_argument("--rate", type=float, default=2,
                   help="Hz de envío (default: 2 — igual que LoRa real)")
    p.add_argument("--noise", action="store_true",
                   help="Agrega líneas de debug como haría el ESP32 (prueba el parser)")
    args = p.parse_args()

    interval = 1.0 / args.rate

    print(f"Abriendo puerto {args.port} a {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
        print(f"  [serial] OK")
    except Exception as e:
        print(f"  [serial] ERROR: {e}")
        print(f"  ¿Está instalado com0com y creado el par COM10<->COM11?")
        sys.exit(1)

    sim = MinibajaSim()
    print(f"\nEnviando a {args.rate} Hz por {args.port} — Ctrl+C para detener")
    print("-" * 60)

    try:
        while True:
            sim.update(interval)
            d = sim.to_lora_dict()

            # Líneas de debug opcionales (simula prints del ESP32)
            if args.noise and sim.msg_count % 10 == 0:
                debug = f"[ESP32] RSSI:-87 SNR:6.5 heap:{random.randint(180000,220000)}\n"
                ser.write(debug.encode("utf-8"))

            # Paquete JSON — termina en \n como haría el ESP32
            line = json.dumps(d) + "\n"
            ser.write(line.encode("utf-8"))

            # Print consola cada segundo
            if sim.msg_count % int(args.rate) == 0:
                print(
                    f"[{d.get('lap',0)} laps] "
                    f"RPM:{d['rpm']:4d}  "
                    f"Speed:{d['speed']:5.1f}km/h  "
                    f"Temp:{d['temp']:5.1f}°C  "
                    f"Vbat:{d['vbat']:.2f}V  "
                    f"GPS:{'OK' if d['gps_fix'] else 'NO'}"
                )

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\nDetenido. {sim.msg_count} paquetes enviados.")
        ser.close()


if __name__ == "__main__":
    main()
