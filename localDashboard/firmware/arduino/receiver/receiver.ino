// MadRams Telemetry — ESP32 Receiver (at pits)
//
// Listens for LoRa packets from the transmitter and forwards each JSON line
// to the host PC via USB serial (115200 baud).  The Python script
// lora_receiver_local.py reads this serial output and writes to InfluxDB.
//
// Uses RadioLib interrupt-driven receive so the ESP32 never blocks in a
// polling loop.  Non-JSON lines (errors, debug) are prefixed with [err].
//
// Dependencies (install via Arduino Library Manager):
//   RadioLib — LoRa driver
//
// Hardware:
//   LoRa module → VSPI (SCK=18, MISO=19, MOSI=23, CS=5, RST=22, DIO0=26)
//   USB serial  → host laptop running lora_receiver_local.py

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>
#include "config.h"

static SX1276 radio = new Module(LORA_CS, LORA_DIO0, LORA_RST, LORA_DIO1);

static volatile bool g_rxFlag = false;

void IRAM_ATTR setRxFlag() {
    g_rxFlag = true;
}

void setup() {
    Serial.begin(115200);
    Serial.println("[boot] MadRams Receiver");

    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);

    int state = radio.begin(LORA_FREQUENCY);
    if (state != RADIOLIB_ERR_NONE) {
        Serial.printf("[err] lora init: %d\n", state);
        while (true) delay(1000);
    }
    radio.setSpreadingFactor(LORA_SF);
    radio.setBandwidth(LORA_BW);
    radio.setCodingRate(LORA_CR);

    radio.setDio0Action(setRxFlag, RISING);
    radio.startReceive();
    Serial.println("[lora] listening...");
}

void loop() {
    if (!g_rxFlag) return;
    g_rxFlag = false;

    String packet;
    int state = radio.readData(packet);

    if (state == RADIOLIB_ERR_NONE) {
        Serial.println(packet); // JSON → forwarded to lora_receiver_local.py
    } else {
        Serial.printf("[err] rx: %d\n", state);
    }

    radio.startReceive();
}
