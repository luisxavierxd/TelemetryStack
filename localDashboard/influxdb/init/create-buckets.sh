#!/bin/bash
# Creates telemetry-analisis bucket on first InfluxDB startup.
# telemetry-live is created automatically via DOCKER_INFLUXDB_INIT_BUCKET.
set -e

influx bucket create \
  --name telemetry-analisis \
  --org "${DOCKER_INFLUXDB_INIT_ORG}" \
  --token "${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN}" \
  --retention 0

echo "[init] bucket created: telemetry-analisis (retention: forever)"
