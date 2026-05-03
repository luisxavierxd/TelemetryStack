// lora_task — transmits latest sensor snapshot via LoRa at 5 Hz
//
// TODO (ESP-IDF driver setup):
//   - Initialize SPI master bus with spi_bus_initialize (VSPI / SPI2_HOST)
//   - Add SX1276 device with spi_bus_add_device
//   - Implement SX1276 register read/write via spi_device_transmit
//   - Configure LoRa mode: SetFrequency, SetSpreadingFactor, SetBandwidth, SetTxPower
//   - Implement blocking transmit: write FIFO, set TX mode, poll for TxDone IRQ
//
// The RadioLib library used in the Arduino version wraps all of the above.
// For ESP-IDF, consider using the community esp-idf-sx127x component or
// porting RadioLib's SPI HAL to ESP-IDF.

#include "lora_task.h"
#include "sensor_task.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "config.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "lora";

void lora_task(void *pvParameters) {
    // TODO: initialize SPI master and SX1276
    ESP_LOGI(TAG, "lora_task started (TX stub — SPI init required)");

    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(200); // 5 Hz

    char json[256];

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        sensor_packet_t snap;
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

        // TODO: transmit json via SX1276 SPI driver
        ESP_LOGD(TAG, "TX: %s", json);
    }
}
