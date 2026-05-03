#!/usr/bin/env python3
"""
Telemetría — Carga datos de SD → telemetry-analisis

Lee un CSV de la SD card, sincroniza timestamps con la telemetría en vivo
usando sample_idx como ancla, y escribe a InfluxDB (bucket: telemetry-analisis).

CSV esperado: sample_idx como primera columna + campos de sensores como floats.
Ejemplo:
    sample_idx,rpm,speed,temp,temp_cvt,vbat,suspension,throttle,lap,gps_fix,lat,lng
    0,1800,22.5,75.0,65.0,12.4,-0.02,45,1,1,20.67,-103.34
    ...

Usage:
    python3 sd_upload.py --run_id run_042 --test suspension_rocks --csv datos.csv
"""

import argparse, csv, os, sys
from pathlib import Path
from statistics import median

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
except ImportError:
    print("Install: pip install influxdb-client")
    sys.exit(1)

INFLUX_URL         = "http://localhost:8086"
INFLUX_TOKEN       = os.environ.get("INFLUX_TOKEN", "")
INFLUX_ORG         = os.environ.get("INFLUX_ORG", "")
INFLUX_MEASUREMENT = os.environ.get("INFLUX_MEASUREMENT", "vehicle")
BUCKET_LIVE        = "telemetry-live"
BUCKET_ANALISIS    = "telemetry-analisis"
SD_INTERVAL_NS     = 100_000_000   # 10 Hz → 100 ms per sample
LORA_INTERVAL_NS   = 200_000_000   # msg_id × this = InfluxDB timestamp (must match receiver)

# Scan up to this many CSV rows looking for valid sensor readings.
# Rows where rpm==0 and temp==0 are skipped (sensors not yet initialized).
SCAN_LIMIT         = 100
# Warn if matched anchor estimates disagree by more than this (ms).
SPREAD_WARN_MS     = 500


def get_live_timestamps(query_api, run_id: str, test: str, live_idxs: list) -> dict:
    """Returns {live_sample_idx: timestamp_ns} for the requested live_idx values."""
    if not live_idxs:
        return {}
    cond = " or ".join(f"r._value == {i}.0" for i in sorted(set(live_idxs)))
    flux = f"""
from(bucket: "{BUCKET_LIVE}")
  |> range(start: 0)
  |> filter(fn: (r) =>
        r._measurement == "{INFLUX_MEASUREMENT}"
        and r.run_id == "{run_id}"
        and r.test == "{test}"
        and r._field == "sample_idx")
  |> filter(fn: (r) => {cond})
"""
    result = {}
    for table in query_api.query(flux, org=INFLUX_ORG):
        for record in table.records:
            idx = int(record.get_value())
            ts_ns = int(record.get_time().timestamp() * 1e9)
            result[idx] = ts_ns
    return result


def load_csv(csv_path: str) -> list:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _sensors_active(row: dict) -> bool:
    """False when rpm and temp are both zero — sensors haven't started yet."""
    try:
        return not (float(row.get("rpm", 0)) == 0.0 and float(row.get("temp", 0)) == 0.0)
    except (ValueError, TypeError):
        return False


def find_anchor(rows: list, query_api, run_id: str, test: str) -> int | None:
    """
    Scan up to SCAN_LIMIT CSV rows, skipping rows where sensors read zero.
    For each valid row, queries InfluxDB for the exact same sample_idx value
    (the ESP32 uses one counter for both msg_id in LoRa and sample_idx in CSV,
    so a live point exists only for samples actually transmitted via LoRa).

    Anchor formula: live_ts[K] - K × LORA_INTERVAL_NS = t_anchor_live (constant).
    SD timestamps:  anchor + sd_idx × SD_INTERVAL_NS.

    Returns None only if no SD row has a matching live point (truly no overlap).
    """
    candidates = [r for r in rows[:SCAN_LIMIT] if _sensors_active(r)]
    if not candidates:
        print(f"  WARN: las primeras {SCAN_LIMIT} filas del CSV no tienen datos de sensores válidos.")
        return None

    # Query the exact same sample_idx values — only LoRa-transmitted samples will match
    sd_idxs = [int(float(r["sample_idx"])) for r in candidates]
    live_ts  = get_live_timestamps(query_api, run_id, test, sd_idxs)

    estimates = []
    for row in candidates:
        sd_idx = int(float(row["sample_idx"]))
        if sd_idx in live_ts:
            # live_ts[sd_idx] = t_anchor_live + sd_idx * LORA_INTERVAL_NS
            # → anchor = t_anchor_live (same constant regardless of which sd_idx matched)
            estimates.append(live_ts[sd_idx] - sd_idx * LORA_INTERVAL_NS)

    if not estimates:
        return None

    spread_ms = (max(estimates) - min(estimates)) / 1_000_000
    print(f"  pares SD↔live encontrados: {len(estimates)}  spread: {spread_ms:.0f} ms")
    if spread_ms > SPREAD_WARN_MS:
        print(f"  ⚠️  spread alto ({spread_ms:.0f} ms) — revisa que el CSV sea del mismo run")

    return int(median(estimates))


def main():
    parser = argparse.ArgumentParser(
        description="Sube datos de SD card → InfluxDB telemetry-analisis"
    )
    parser.add_argument("--run_id", required=True, help="ID de la corrida, ej: run_042")
    parser.add_argument("--test",   required=True, help="Nombre del test, ej: suspension_rocks")
    parser.add_argument("--csv",    required=True, help="Ruta al CSV de la SD card")
    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"ERROR: archivo no encontrado: {args.csv}")
        sys.exit(1)

    client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()
    write_api = client.write_api(write_options=SYNCHRONOUS)

    rows = load_csv(args.csv)
    if not rows:
        print("ERROR: el CSV está vacío.")
        client.close()
        sys.exit(1)
    print(f"CSV cargado: {len(rows)} filas")

    print(f"Buscando ancla en {BUCKET_LIVE} (run_id={args.run_id}, test={args.test})...")
    anchor = find_anchor(rows, query_api, args.run_id, args.test)

    if anchor is None:
        print("  ❌ no se encontró coincidencia entre CSV y live — abortando")
        print(f"  Verifica que la corrida en vivo esté registrada con run_id={args.run_id} test={args.test}")
        print(f"  y que el CSV tenga datos con sensores activos en las primeras {SCAN_LIMIT} filas.")
        client.close()
        sys.exit(1)

    print(f"  ✅ ancla calculada: {anchor} ns")

    # ── Escribir a telemetry-analisis ─────────────────────────────────────────
    print(f"\nEscribiendo {len(rows)} puntos a {BUCKET_ANALISIS}...")
    points = []
    for row in rows:
        sd_idx = int(float(row["sample_idx"]))
        ts_ns  = anchor + sd_idx * SD_INTERVAL_NS
        p = (Point(INFLUX_MEASUREMENT)
             .tag("run_id", args.run_id)
             .tag("test",   args.test)
             .tag("source", "sd")
             .field("sample_idx", sd_idx)
             .time(ts_ns, write_precision="ns")
        )
        for col, val in row.items():
            if col == "sample_idx":
                continue
            try:
                p = p.field(col, float(val))
            except (ValueError, TypeError):
                pass
        points.append(p)

    try:
        write_api.write(bucket=BUCKET_ANALISIS, record=points)
        print(f"  ✅ {len(points)} puntos escritos a {BUCKET_ANALISIS}")
    except Exception as e:
        print(f"  ERROR al escribir: {e}")
        client.close()
        sys.exit(1)

    client.close()


if __name__ == "__main__":
    main()
