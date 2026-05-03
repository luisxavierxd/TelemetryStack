#!/bin/bash
# Creates extra buckets on first InfluxDB startup.
# Telemetry bucket (DOCKER_INFLUXDB_INIT_BUCKET) is created automatically by the image.
set -e

for bucket in telemetry-live telemetry-analisis; do
  influx bucket create \
    --name "${bucket}" \
    --org "${DOCKER_INFLUXDB_INIT_ORG}" \
    --token "${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN}" \
    --retention 0
  echo "[init] bucket created: ${bucket} (retention: forever)"
done
