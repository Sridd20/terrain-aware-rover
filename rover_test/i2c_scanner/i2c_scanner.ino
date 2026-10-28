// I2C Scanner — paste into Arduino IDE and upload to ESP32
// Opens Serial Monitor at 115200 baud to see results

#include <Wire.h>

void setup() {
    Serial.begin(115200);
    delay(1000);
    Wire.begin(21, 22);   // SDA=21, SCL=22 (same as rover firmware)
    Serial.println("\n=== I2C Scanner ===");
}

void loop() {
    byte count = 0;
    Serial.println("Scanning...");

    for (byte addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        byte err = Wire.endTransmission();

        if (err == 0) {
            Serial.printf("  Found device at 0x%02X", addr);
            if (addr == 0x3C || addr == 0x3D) Serial.print("  <-- OLED (SSD1306)");
            if (addr == 0x68 || addr == 0x69) Serial.print("  <-- MPU6050");
            Serial.println();
            count++;
        }
    }

    if (count == 0)
        Serial.println("  No I2C devices found! Check wiring.");
    else
        Serial.printf("  Total: %d device(s) found\n", count);

    Serial.println("---");
    delay(3000);
}
