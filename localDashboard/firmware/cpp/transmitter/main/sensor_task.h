#pragma once
#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

typedef struct {
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
} sensor_packet_t;

// Populated each sample period; consumed by lora_task and sd_task.
// latest_mutex must be held before reading/writing g_latest.
extern sensor_packet_t  g_latest;
extern SemaphoreHandle_t g_latest_mutex;
extern QueueHandle_t     g_sd_queue;

// Entry point for xTaskCreatePinnedToCore (core 1, 10 Hz)
void sensor_task(void *pvParameters);
