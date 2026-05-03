// sd_task — writes sensor samples to CSV on SD card at 10 Hz
//
// TODO (ESP-IDF driver setup):
//   - Initialize HSPI bus with spi_bus_initialize (HSPI / SPI3_HOST)
//   - Mount FAT filesystem on SD card using esp_vfs_fat_sdspi_mount
//   - After mount, use standard fopen/fprintf/fflush (VFS mapped to /sdcard)
//
// The SD.h library used in the Arduino version wraps all of the above.
// For ESP-IDF, use the sdmmc component with SPI mode:
//   sdmmc_host_t host = SDSPI_HOST_DEFAULT();
//   sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
//   esp_vfs_fat_sdspi_mount("/sdcard", &host, &slot, &mount_config, &card);

#include "sd_task.h"
#include "sensor_task.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "config.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "sd";

void sd_task(void *pvParameters) {
    // TODO: mount SD card via esp_vfs_fat_sdspi_mount
    ESP_LOGI(TAG, "sd_task started (write stub — SD mount required)");

    // TODO: open /sdcard/run_XXXX.csv for writing, write CSV header
    FILE *f = NULL; // placeholder

    sensor_packet_t pkt;
    char line[256];

    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(100); // 10 Hz

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        while (xQueueReceive(g_sd_queue, &pkt, 0) == pdTRUE) {
            snprintf(line, sizeof(line),
                "%lu,%.1f,%.1f,%.1f,%.1f,%.2f,%.4f,%.1f,%.7f,%.7f,%d,%d\n",
                (unsigned long)pkt.msg_id, pkt.rpm, pkt.speed,
                pkt.temp, pkt.temp_cvt, pkt.vbat,
                pkt.suspension, pkt.throttle,
                pkt.lat, pkt.lng,
                pkt.gps_fix, pkt.lap
            );

            if (f) {
                fputs(line, f);
            } else {
                // TODO: remove this branch once SD is mounted
                ESP_LOGD(TAG, "%s", line);
            }
        }

        if (f) fflush(f);
    }
}
