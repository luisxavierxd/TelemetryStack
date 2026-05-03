// sensor_task — reads all sensors at 10 Hz
//
// TODO (ESP-IDF driver setup):
//   - adc1_config_width / adc1_config_channel_atten for each ADC pin
//   - uart_param_config + uart_driver_install for GPS UART
//   - gpio_config + gpio_isr_handler_add for RPM interrupt
//   - Implement NMEA parser (TinyGPSPlus can be ported; or use esp_nmea_parser component)
//   - Implement NTC temperature conversion using adc1_get_raw

#include "sensor_task.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "config.h"
#include <string.h>

static const char *TAG = "sensor";

static volatile uint32_t g_rpmPulses = 0;
static uint32_t g_msgId = 0;

static void IRAM_ATTR rpm_isr(void *arg) {
    g_rpmPulses++;
}

void sensor_task(void *pvParameters) {
    // TODO: initialize ADC channels (adc1_config_width, adc1_config_channel_atten)
    // TODO: initialize GPIO interrupt for RPM (gpio_config, gpio_isr_handler_add)
    // TODO: initialize UART2 for GPS (uart_param_config, uart_driver_install)
    ESP_LOGI(TAG, "sensor_task started");

    TickType_t xLastWake = xTaskGetTickCount();
    const TickType_t kPeriod = pdMS_TO_TICKS(100); // 10 Hz
    uint32_t lastMs = xTaskGetTickCount() * portTICK_PERIOD_MS;

    while (true) {
        vTaskDelayUntil(&xLastWake, kPeriod);

        uint32_t nowMs    = xTaskGetTickCount() * portTICK_PERIOD_MS;
        uint32_t elapsed  = nowMs - lastMs;
        uint32_t pulses   = g_rpmPulses;
        g_rpmPulses       = 0;
        lastMs            = nowMs;

        sensor_packet_t pkt;
        memset(&pkt, 0, sizeof(pkt));

        pkt.msg_id = g_msgId++;
        pkt.rpm    = (elapsed > 0)
            ? (pulses * 60000.0f / elapsed / RPM_PULSES_PER_REV)
            : 0.0f;

        // TODO: replace with adc1_get_raw and conversion formulas
        pkt.speed      = 0.0f;
        pkt.temp       = 0.0f;   // TODO: NTC conversion
        pkt.temp_cvt   = 0.0f;   // TODO: NTC conversion
        pkt.vbat       = 0.0f;   // TODO: ADC × VBAT_DIVIDER
        pkt.suspension = 0.0f;   // TODO: ADC mapping
        pkt.throttle   = 0.0f;   // TODO: ADC mapping

        // TODO: parse GPS UART data and populate lat/lng/gps_fix
        pkt.lat     = 0.0;
        pkt.lng     = 0.0;
        pkt.gps_fix = 0;
        pkt.lap     = 0;

        xSemaphoreTake(g_latest_mutex, portMAX_DELAY);
        g_latest = pkt;
        xSemaphoreGive(g_latest_mutex);

        xQueueSend(g_sd_queue, &pkt, 0);
    }
}
