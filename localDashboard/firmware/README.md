# Firmware — ESP32 Transmitter & Receiver

Two ESP32 boards run the radio link:

| Board | Role | Location |
|---|---|---|
| **Transmitter** | Reads sensors, writes SD card, sends LoRa JSON | On the vehicle |
| **Receiver** | Receives LoRa packets, forwards JSON over USB serial | At pits, connected to laptop |

The laptop runs `lora_receiver_local.py` which reads the JSON from USB serial and writes it to InfluxDB.

---

## Folder structure

```
firmware/
├── arduino/
│   ├── transmitter/
│   │   ├── transmitter.ino     ← complete, ready to flash
│   │   └── config.h.example    ← copy to config.h and fill in your pins
│   └── receiver/
│       ├── receiver.ino        ← complete, ready to flash
│       └── config.h.example
└── cpp/
    ├── transmitter/
    │   ├── CMakeLists.txt
    │   ├── config.h.example
    │   └── main/
    │       ├── CMakeLists.txt
    │       ├── main.cpp
    │       ├── sensor_task.h / .cpp   ← structure complete; ADC/UART/GPIO init TODOs
    │       ├── lora_task.h   / .cpp   ← structure complete; SPI/SX1276 init TODOs
    │       └── sd_task.h     / .cpp   ← structure complete; VFS/SD mount TODOs
    └── receiver/
        ├── CMakeLists.txt
        ├── config.h.example
        └── main/
            └── main.cpp               ← structure complete; SPI/SX1276 init TODOs
```

`config.h` files are **gitignored**.  Copy the `.example` file, rename it to `config.h`, and fill in your pin numbers and calibration values.

---

## Arduino (recommended for competition use)

The Arduino version is **complete and ready to flash**.  It uses FreeRTOS tasks (available in the ESP32 Arduino core) and the standard Arduino ecosystem libraries.

### Setup

1. Install [Arduino IDE](https://www.arduino.cc/en/software) with the ESP32 board package:
   - Board Manager URL: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - Board: **ESP32 Dev Module**

2. Install libraries via Library Manager (`Sketch → Include Library → Manage Libraries`):
   - **RadioLib** (by Jan Gromeš)
   - **TinyGPSPlus** (by Mikal Hart)
   - SD is included in the ESP32 Arduino core

3. Copy and fill `config.h`:
   ```
   cd firmware/arduino/transmitter
   cp config.h.example config.h
   # Edit config.h with your pin numbers and calibration values
   ```

4. Open `transmitter.ino` in Arduino IDE, select the correct COM port, and flash.

5. Repeat steps 3–4 for `receiver/`.

### FreeRTOS task architecture

```
Core 0                          Core 1
──────────────────────          ──────────────────────────────────
taskLoRaSend  (5 Hz)            taskSampler  (10 Hz)
  reads g_latest via mutex        reads all sensors
  formats JSON                    updates g_latest (mutex)
  calls radio.transmit()          pushes to g_sd_queue
                                taskSDWrite  (10 Hz)
                                  drains g_sd_queue
                                  writes CSV rows
                                  calls f.flush()
```

**Why two cores?** `radio.transmit()` is a blocking SPI call that can take 70–300 ms depending on SF/BW.  Running it on core 0 means it never blocks the 10 Hz sensor sampling on core 1.

**Separate SPI buses**: LoRa uses VSPI (SCK=18/MISO=19/MOSI=23) and SD uses HSPI (SCK=14/MISO=12/MOSI=13).  No mutex needed between them because the ESP32 hardware SPI controllers are independent.

### LoRa speed vs range

The configuration in `config.h.example` uses SF7/BW500 which transmits a 180-byte JSON in ~72 ms, supporting 5 Hz.

| SF | BW (kHz) | Air time (180 B) | Max rate | Range |
|---|---|---|---|---|
| 7 | 500 | ~72 ms | ~13 Hz | short (<500 m) |
| 7 | 125 | ~287 ms | ~3 Hz | medium |
| 9 | 125 | ~370 ms | ~2 Hz | long (>1 km) |
| 12 | 125 | ~2700 ms | <1 Hz | very long |

For Minibaja SAE competition (track size ~100–500 m), SF7/BW500 is the right choice.

---

## C++ / ESP-IDF (future migration)

The C++ version shares the same task architecture and data structures as the Arduino version but uses ESP-IDF native drivers instead of Arduino wrappers.  The task skeletons and FreeRTOS calls are complete; driver initialization is marked `TODO` in each task file.

### What is implemented
- `main.cpp`: `app_main()`, queue/mutex creation, task pinning
- `sensor_task.h/.cpp`: `sensor_packet_t` struct, task loop, RPM counting, JSON formatting logic
- `lora_task.cpp`: 5 Hz timing, mutex-protected snapshot read, JSON formatting
- `sd_task.cpp`: 10 Hz timing, queue drain, CSV row formatting

### What needs implementing (TODOs)
- `sensor_task.cpp`: `adc1_config_width`, `adc1_get_raw`, `uart_driver_install` (GPS), `gpio_isr_handler_add` (RPM)
- `lora_task.cpp`: `spi_bus_initialize` + SX1276 register driver (or integrate [esp-idf-sx127x](https://github.com/nopnop2002/esp-idf-sx127x))
- `sd_task.cpp`: `esp_vfs_fat_sdspi_mount` for SD card VFS

### Setup

1. Install [ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/get-started/) v5.x.
2. Copy and fill `config.h`:
   ```bash
   cd firmware/cpp/transmitter
   cp config.h.example config.h
   ```
3. Build and flash:
   ```bash
   idf.py build
   idf.py -p /dev/ttyUSB0 flash monitor
   ```

---

## JSON packet format

Both firmware versions produce the same JSON on serial (receiver) and CSV (transmitter SD card):

**Serial / LoRa (receiver → laptop):**
```json
{"msg_id":42,"rpm":2100.0,"speed":35.0,"temp":82.0,"temp_cvt":75.0,
 "vbat":12.40,"suspension":-0.050,"throttle":60.0,
 "lat":20.673600,"lng":-103.344000,"gps_fix":1,"lap":3}
```

**CSV (transmitter SD card):**
```
sample_idx,rpm,speed,temp,temp_cvt,vbat,suspension,throttle,lat,lng,gps_fix,lap
42,2100.0,35.0,82.0,75.0,12.40,-0.0500,60.0,20.6736000,-103.3440000,1,3
```

`msg_id` in JSON = `sample_idx` in CSV.  The Python script `sd_upload.py` uses this to synchronize SD data timestamps with the live LoRa data in InfluxDB.

---

## config.h fields

| Field | Transmitter | Receiver | Description |
|---|---|---|---|
| `LORA_SCK/MISO/MOSI/CS/RST/DIO0/DIO1` | both | both | SX1276 wiring |
| `LORA_FREQUENCY` | both | both | MHz — must match on both boards |
| `LORA_SF/BW/CR` | both | both | Must match on both boards |
| `LORA_POWER` | TX only | — | dBm output power |
| `SD_SCK/MISO/MOSI/CS` | TX only | — | SD card HSPI wiring |
| `GPS_RX/TX/BAUD` | TX only | — | GPS module UART |
| `PIN_RPM` | TX only | — | Hall effect / reed switch input |
| `RPM_PULSES_PER_REV` | TX only | — | Pulses per shaft revolution |
| `PIN_TEMP_ENGINE/CVT` | TX only | — | NTC thermistor ADC pins |
| `NTC_BETA/R25/RSERIES` | TX only | — | NTC calibration |
| `PIN_VBAT / VBAT_DIVIDER` | TX only | — | Battery voltage divider |
| `PIN_SUSPENSION / SUSPENSION_RANGE` | TX only | — | Potentiometer range in meters |
| `PIN_THROTTLE` | TX only | — | TPS ADC pin |
