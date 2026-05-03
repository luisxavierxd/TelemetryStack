#pragma once
#include "freertos/FreeRTOS.h"

// Entry point for xTaskCreatePinnedToCore (core 0, 5 Hz)
void lora_task(void *pvParameters);
