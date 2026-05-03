// MadRams Live Telemetry — ESP32 Transmitter
//
// Reads sensors and writes directly to InfluxDB Cloud over WiFi.
// No LoRa radio, no receiver ESP32 — just the vehicle ESP32 + phone hotspot.
//
// Two FreeRTOS tasks:
//   taskSampler (core 1, 10 Hz) — reads all sensors, updates shared state
//   taskSend    (core 0,  5 Hz) — reads shared state, writes to InfluxDB Cloud
//
// Dependencies (install via Arduino Library Manager):
//   ESP32 InfluxDB  (by Tobias Kopecek) — InfluxDB Cloud HTTPS client
//   TinyGPSPlus     (by Mikal Hart)     — NMEA GPS parser
//
// Hardware: same sensor wiring as localDashboard transmitter.
// No LoRa module or SD card needed.

#include <Arduino.h>
#include <WiFi.h>
#include <InfluxDbClient.h>
#include <InfluxDbCloud.h>
#include <TinyGPSPlus.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "config.h"

// ─── Data structure ───────────────────────────────────────────────────────────

struct SensorSnapshot {
    uint32_t msg_id;
    float    rpm, speed, temp, temp_cvt, vbat, suspension, throttle;
    double   lat, lng;
    uint8_t  gps_fix, lap;
};

static SensorSnapshot     g_latest = {};
static SemaphoreHandle_t  g_mutex;

// ─── InfluxDB client ──────────────────────────────────────────────────────────

static InfluxDBClient g_influx(INFLUX_URL, INFLUX_ORG, INFLUX_BUCKET, INFLUX_TOKEN,
                                InfluxDbCloud2CACert);
static Point g_point(INFLUX_MEASUREMENT);

// ─── GPS ──────────────────────────────────────────────────────────────────────

static HardwareSerial gpsSerial(2);
static TinyGPSPlus    gps;

// ─── RPM ──────────────────────────────────────────────────────────────────────

static volatile uint32_t g_rpmPulses = 0;
static uint32_t          g_lastRpmMs = 0;
static uint32_t          g_msgId     = 0;

void IRAM_ATTR onRpmPulse() { g_rpmPulses++; }

static float readTemp(int pin) {
    int raw = analogRead(pin);
    if (raw == 0) return -999.0f;
    float v = (raw / 4095.0f) * 3.3f;
    float r = NTC_RSERIES * v / (3.3f - v);
    float K = 1.0f / (logf(r / NTC_R25) / NTC_BETA + 1.0f / 298.15f);
    return K - 273.15f;
}

// ─── Task: sensor sampling at 10 Hz ──────────────────────────────────────────

void taskSampler(void *pvParameters) {
    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(100);

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        uint32_t nowMs   = millis();
        uint32_t pulses  = g_rpmPulses; g_rpmPulses = 0;
        uint32_t elapsed = nowMs - g_lastRpmMs; g_lastRpmMs = nowMs;

        while (gpsSerial.available()) gps.encode(gpsSerial.read());

        SensorSnapshot snap;
        snap.msg_id     = g_msgId++;
        snap.rpm        = (elapsed > 0) ? (pulses * 60000.0f / elapsed / RPM_PULSES_PER_REV) : 0.0f;
        snap.speed      = 0.0f;
        snap.temp       = readTemp(PIN_TEMP_ENGINE);
        snap.temp_cvt   = readTemp(PIN_TEMP_CVT);
        snap.vbat       = (analogRead(PIN_VBAT) / 4095.0f) * 3.3f * VBAT_DIVIDER;
        snap.suspension = (analogRead(PIN_SUSPENSION) / 4095.0f - 0.5f) * SUSPENSION_RANGE;
        snap.throttle   = (analogRead(PIN_THROTTLE)   / 4095.0f) * 100.0f;
        snap.lat        = gps.location.lat();
        snap.lng        = gps.location.lng();
        snap.gps_fix    = gps.location.isValid() ? 1 : 0;
        snap.lap        = 0;

        xSemaphoreTake(g_mutex, portMAX_DELAY);
        g_latest = snap;
        xSemaphoreGive(g_mutex);
    }
}

// ─── Task: write to InfluxDB Cloud at 5 Hz ───────────────────────────────────

void taskSend(void *pvParameters) {
    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(200);

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        // Reconnect WiFi if dropped (phone moved / signal lost)
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[wifi] reconnecting...");
            WiFi.reconnect();
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        SensorSnapshot snap;
        xSemaphoreTake(g_mutex, portMAX_DELAY);
        snap = g_latest;
        xSemaphoreGive(g_mutex);

        g_point.clearFields();
        g_point.addField("msg_id",     (long)snap.msg_id);
        g_point.addField("rpm",        snap.rpm);
        g_point.addField("speed",      snap.speed);
        g_point.addField("temp",       snap.temp);
        g_point.addField("temp_cvt",   snap.temp_cvt);
        g_point.addField("vbat",       snap.vbat);
        g_point.addField("suspension", snap.suspension);
        g_point.addField("throttle",   snap.throttle);
        g_point.addField("gps_fix",    (int)snap.gps_fix);
        g_point.addField("lap",        (int)snap.lap);
        if (snap.gps_fix) {
            g_point.addField("lat", snap.lat);
            g_point.addField("lng", snap.lng);
        }

        if (!g_influx.writePoint(g_point)) {
            Serial.println("[influx] write failed: " + g_influx.getLastErrorMessage());
        }
    }
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n[boot] MadRams Live Transmitter");

    // WiFi
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[wifi] connecting");
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.println("\n[wifi] OK — " + WiFi.localIP().toString());

    // NTP time sync (required for InfluxDB Cloud timestamps)
    timeSync(TZ_INFO, "pool.ntp.org", "time.nis.gov");

    // InfluxDB connection check
    if (g_influx.validateConnection()) {
        Serial.println("[influx] OK — " + g_influx.getServerUrl());
    } else {
        Serial.println("[influx] WARN: " + g_influx.getLastErrorMessage());
    }

    // Tags set once; fields updated each write
    g_point.addTag("device", "vehicle");
    g_point.addTag("team",   TEAM_NAME);

    // Sensors
    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX, GPS_TX);
    pinMode(PIN_RPM, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_RPM), onRpmPulse, FALLING);
    g_lastRpmMs = millis();
    analogReadResolution(12);

    g_mutex = xSemaphoreCreateMutex();

    xTaskCreatePinnedToCore(taskSampler, "sampler",  4096, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(taskSend,    "influx_tx", 4096, NULL, 2, NULL, 0);
}

void loop() {
    vTaskDelay(portMAX_DELAY);
}
