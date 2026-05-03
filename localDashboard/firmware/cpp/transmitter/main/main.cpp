// MadRams Telemetry — ESP32 Transmitter (ESP-IDF / C++)
//
// Three FreeRTOS tasks:
//   sensor_task (core 1, 10 Hz) — reads sensors, updates g_latest + g_sd_queue
//   lora_task   (core 0,  5 Hz) — reads g_latest, transmits LoRa JSON
//   sd_task     (core 1, 10 Hz) — drains g_sd_queue, writes CSV to SD card

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "sensor_task.h"
#include "lora_task.h"
#include "sd_task.h"

static const char *TAG = "main";

// Shared globals — defined here, declared extern in sensor_task.h
sensor_packet_t  g_latest       = {};
SemaphoreHandle_t g_latest_mutex = NULL;
QueueHandle_t     g_sd_queue     = NULL;

extern "C" void app_main(void) {
    ESP_LOGI(TAG, "MadRams Telemetry — Transmitter");

    g_latest_mutex = xSemaphoreCreateMutex();
    g_sd_queue     = xQueueCreate(20, sizeof(sensor_packet_t));
    configASSERT(g_latest_mutex);
    configASSERT(g_sd_queue);

    // sensor_task and sd_task share core 1 to keep SPI (SD) off core 0
    xTaskCreatePinnedToCore(sensor_task, "sampler",  4096, NULL, 3, NULL, 1);
    xTaskCreatePinnedToCore(lora_task,   "lora_tx",  4096, NULL, 2, NULL, 0);
    xTaskCreatePinnedToCore(sd_task,     "sd_write", 4096, NULL, 1, NULL, 1);
}
