#pragma once
#include "freertos/FreeRTOS.h"

// Entry point for xTaskCreatePinnedToCore (core 1, 10 Hz)
void sd_task(void *pvParameters);
