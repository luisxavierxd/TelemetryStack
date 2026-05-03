// MadRams Telemetry — ESP32 Transmitter (on vehicle)
//
// Three FreeRTOS tasks:
//   taskSampler  (core 1, 10 Hz) — reads all sensors, writes to shared struct + SD queue
//   taskLoRaSend (core 0,  5 Hz) — sends latest sensor snapshot as LoRa JSON
//   taskSDWrite  (core 1, 10 Hz) — consumes SD queue and writes rows to CSV
//
// Dependencies (install via Arduino Library Manager):
//   RadioLib    — LoRa driver
//   TinyGPSPlus — NMEA parser
//   SD          — SD card (built into ESP32 Arduino core)
//
// Hardware:
//   LoRa module  → VSPI (SCK=18, MISO=19, MOSI=23, CS=5, RST=22, DIO0=26)
//   SD card      → HSPI (SCK=14, MISO=12, MOSI=13, CS=15)
//   GPS module   → UART2 (RX=16, TX=17)
//   RPM sensor   → GPIO 34 (interrupt, hall effect / reed switch)
//   Thermistors  → ADC pins 32 (engine), 33 (CVT)
//   Battery      → ADC pin 35 (voltage divider)
//   Suspension   → ADC pin 36 (potentiometer)
//   Throttle     → ADC pin 39 (TPS)

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include <TinyGPSPlus.h>
#include <SD.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "config.h"

// ─── Data structures ──────────────────────────────────────────────────────────

struct SensorPacket {
    uint32_t msg_id;
    float    rpm;
    float    speed;
    float    temp;
    float    temp_cvt;
    float    vbat;
    float    suspension;
    float    throttle;
    double   lat;
    double   lng;
    uint8_t  gps_fix;
    uint8_t  lap;
};

// ─── Globals ──────────────────────────────────────────────────────────────────

// Latest sample shared between taskSampler → taskLoRaSend
static SensorPacket      g_latest;
static SemaphoreHandle_t g_latest_mutex;

// FIFO queue from taskSampler → taskSDWrite (depth = 2 s @ 10 Hz)
static QueueHandle_t     g_sd_queue;

// LoRa on VSPI (default SPI bus)
static SX1276 radio = new Module(LORA_CS, LORA_DIO0, LORA_RST, LORA_DIO1);

// GPS on UART2
static HardwareSerial gpsSerial(2);
static TinyGPSPlus    gps;

// RPM counter (ISR-updated)
static volatile uint32_t g_rpmPulses   = 0;
static uint32_t          g_lastRpmMs   = 0;

// Running message ID (monotonic counter used by Python receiver for timestamps)
static uint32_t g_msgId = 0;

// SD uses HSPI (independent SPI bus — no contention with LoRa)
static SPIClass g_spiSD(HSPI);

// ─── Helpers ──────────────────────────────────────────────────────────────────

void IRAM_ATTR onRpmPulse() {
    g_rpmPulses++;
}

// NTC thermistor reading via Steinhart-Hart β approximation
static float readTemp(int pin) {
    int   raw = analogRead(pin);
    if (raw == 0) return -999.0f;
    float v   = (raw / 4095.0f) * 3.3f;
    float r   = NTC_RSERIES * v / (3.3f - v);
    float K   = 1.0f / (logf(r / NTC_R25) / NTC_BETA + 1.0f / 298.15f);
    return K - 273.15f;
}

// ─── Task: sensor sampling at 10 Hz ──────────────────────────────────────────

void taskSampler(void *pvParameters) {
    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(100);

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        // RPM — pulse count since last call divided by elapsed time
        uint32_t nowMs   = millis();
        uint32_t pulses  = g_rpmPulses;
        g_rpmPulses      = 0;
        uint32_t elapsedMs = nowMs - g_lastRpmMs;
        g_lastRpmMs = nowMs;
        float rpm = (elapsedMs > 0)
            ? (pulses * 60000.0f / elapsedMs / RPM_PULSES_PER_REV)
            : 0.0f;

        // GPS — drain UART buffer
        while (gpsSerial.available()) gps.encode(gpsSerial.read());

        SensorPacket pkt;
        pkt.msg_id     = g_msgId++;
        pkt.rpm        = rpm;
        pkt.speed      = 0.0f; // derive from wheel encoder or GPS speed if available
        pkt.temp       = readTemp(PIN_TEMP_ENGINE);
        pkt.temp_cvt   = readTemp(PIN_TEMP_CVT);
        pkt.vbat       = (analogRead(PIN_VBAT) / 4095.0f) * 3.3f * VBAT_DIVIDER;
        pkt.suspension = (analogRead(PIN_SUSPENSION) / 4095.0f - 0.5f) * SUSPENSION_RANGE;
        pkt.throttle   = (analogRead(PIN_THROTTLE)   / 4095.0f) * 100.0f;
        pkt.lat        = gps.location.lat();
        pkt.lng        = gps.location.lng();
        pkt.gps_fix    = gps.location.isValid() ? 1 : 0;
        pkt.lap        = 0; // implement lap detection logic here if needed

        // Update shared latest (for LoRa task)
        xSemaphoreTake(g_latest_mutex, portMAX_DELAY);
        g_latest = pkt;
        xSemaphoreGive(g_latest_mutex);

        // Enqueue for SD (non-blocking: drop sample if SD is falling behind)
        xQueueSend(g_sd_queue, &pkt, 0);
    }
}

// ─── Task: LoRa transmission at 5 Hz ─────────────────────────────────────────

void taskLoRaSend(void *pvParameters) {
    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(200);

    char json[256];

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        SensorPacket snap;
        xSemaphoreTake(g_latest_mutex, portMAX_DELAY);
        snap = g_latest;
        xSemaphoreGive(g_latest_mutex);

        snprintf(json, sizeof(json),
            "{\"msg_id\":%lu,\"rpm\":%.1f,\"speed\":%.1f,\"temp\":%.1f,"
            "\"temp_cvt\":%.1f,\"vbat\":%.2f,\"suspension\":%.3f,"
            "\"throttle\":%.1f,\"lat\":%.6f,\"lng\":%.6f,"
            "\"gps_fix\":%d,\"lap\":%d}",
            (unsigned long)snap.msg_id, snap.rpm, snap.speed,
            snap.temp, snap.temp_cvt, snap.vbat,
            snap.suspension, snap.throttle,
            snap.lat, snap.lng,
            snap.gps_fix, snap.lap
        );

        int state = radio.transmit(json);
        if (state != RADIOLIB_ERR_NONE) {
            Serial.printf("[lora] tx error: %d\n", state);
        }
    }
}

// ─── Task: SD card write at 10 Hz ────────────────────────────────────────────

void taskSDWrite(void *pvParameters) {
    g_spiSD.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);

    if (!SD.begin(SD_CS, g_spiSD)) {
        Serial.println("[sd] mount failed — SD task exiting");
        vTaskDelete(NULL);
        return;
    }

    // Pick a new filename each boot to avoid overwriting previous sessions
    char filename[32];
    for (int i = 0; i < 1000; i++) {
        snprintf(filename, sizeof(filename), "/run_%04d.csv", i);
        if (!SD.exists(filename)) break;
    }

    File f = SD.open(filename, FILE_WRITE);
    if (!f) {
        Serial.printf("[sd] cannot open %s\n", filename);
        vTaskDelete(NULL);
        return;
    }
    f.println("sample_idx,rpm,speed,temp,temp_cvt,vbat,suspension,throttle,lat,lng,gps_fix,lap");
    Serial.printf("[sd] logging to %s\n", filename);

    SensorPacket pkt;
    char line[256];

    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(100);

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        // Drain whatever samples arrived since last wake
        while (xQueueReceive(g_sd_queue, &pkt, 0) == pdTRUE) {
            snprintf(line, sizeof(line),
                "%lu,%.1f,%.1f,%.1f,%.1f,%.2f,%.4f,%.1f,%.7f,%.7f,%d,%d",
                (unsigned long)pkt.msg_id, pkt.rpm, pkt.speed,
                pkt.temp, pkt.temp_cvt, pkt.vbat,
                pkt.suspension, pkt.throttle,
                pkt.lat, pkt.lng,
                pkt.gps_fix, pkt.lap
            );
            f.println(line);
        }
        f.flush();
    }
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n[boot] MadRams Transmitter");

    // GPS
    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX, GPS_TX);

    // RPM interrupt
    pinMode(PIN_RPM, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_RPM), onRpmPulse, FALLING);
    g_lastRpmMs = millis();

    // ADC
    analogReadResolution(12);

    // LoRa (VSPI)
    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
    int state = radio.begin(LORA_FREQUENCY);
    if (state != RADIOLIB_ERR_NONE) {
        Serial.printf("[lora] init failed: %d\n", state);
        while (true) delay(1000);
    }
    radio.setSpreadingFactor(LORA_SF);
    radio.setBandwidth(LORA_BW);
    radio.setCodingRate(LORA_CR);
    radio.setOutputPower(LORA_POWER);
    Serial.println("[lora] OK");

    // Sync primitives
    g_latest_mutex = xSemaphoreCreateMutex();
    g_sd_queue     = xQueueCreate(20, sizeof(SensorPacket));

    // Tasks — sampler and SD share core 1; LoRa TX on core 0
    xTaskCreatePinnedToCore(taskSampler,  "sampler",  4096, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(taskLoRaSend, "lora_tx",  4096, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(taskSDWrite,  "sd_write", 4096, NULL, 1, NULL, 1);
}

void loop() {
    // All work happens in FreeRTOS tasks; loop() is never needed.
    vTaskDelay(portMAX_DELAY);
}
