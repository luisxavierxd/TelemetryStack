// MadRams Telemetry — ESP32 Receiver (ESP-IDF / C++)
//
// Listens for LoRa packets from the transmitter and forwards each JSON line
// to the host PC via UART0 (USB serial, 115200 baud).
//
// TODO (ESP-IDF driver setup):
//   - Initialize SPI master bus with spi_bus_initialize (SPI2_HOST / VSPI)
//   - Add SX1276 device with spi_bus_add_device
//   - Configure LoRa in continuous receive mode
//   - Attach GPIO interrupt on DIO0 to detect RxDone
//   - On RxDone IRQ: read FIFO via SPI, print JSON to UART0
//
// The Arduino version (receiver.ino) is fully functional and uses RadioLib
// for all of the above.  This C++ version mirrors the same logic; driver
// initialization is left as TODOs pending SX1276 ESP-IDF component selection.

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/uart.h"
#include "config.h"

static const char *TAG = "receiver";

// Packet buffer — SX1276 FIFO max is 256 bytes
static char g_packet[256];

static void lora_rx_task(void *pvParameters) {
    // TODO: initialize SPI master bus for SX1276 (see transmitter lora_task.cpp)
    // TODO: configure SX1276 — frequency, SF, BW, CR, continuous RX mode
    // TODO: attach GPIO interrupt on DIO0 (RxDone flag)
    ESP_LOGI(TAG, "lora_rx_task started (RX stub — SPI init required)");

    while (true) {
        // TODO: wait on RxDone semaphore posted by DIO0 ISR
        // TODO: read packet from SX1276 FIFO into g_packet
        // TODO: check CRC; if valid, print g_packet via uart_write_bytes(UART_NUM_0, ...)
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

extern "C" void app_main(void) {
    ESP_LOGI(TAG, "MadRams Telemetry — Receiver");

    // UART0 is already initialized by the IDF startup for logging;
    // reuse it at 115200 for forwarding JSON to the host PC.

    xTaskCreatePinnedToCore(lora_rx_task, "lora_rx", 4096, NULL, 2, NULL, 0);
}
