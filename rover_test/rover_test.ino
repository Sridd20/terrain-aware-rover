/*
 * rover_test.ino  (v3 — bare minimum)
 * Drives pins directly, no functions, no complexity.
 * Uses ORIGINAL pin assignments from rover_firmware.ino.
 *
 * Physical wiring (as per rover_firmware.ino):
 *   GPIO 27 → L298N IN1  (LEFT  dir A)
 *   GPIO 26 → L298N IN2  (LEFT  dir B)
 *   GPIO 14 → L298N ENA  (LEFT  PWM)
 *   GPIO 25 → L298N IN3  (RIGHT dir A)
 *   GPIO 33 → L298N IN4  (RIGHT dir B)
 *   GPIO 13 → L298N ENB  (RIGHT PWM)
 *
 * Serial: 115200 baud
 */

void setup() {
    Serial.begin(115200);
    delay(1000);

    // Set all motor pins as outputs
    pinMode(27, OUTPUT); pinMode(26, OUTPUT); pinMode(14, OUTPUT);
    pinMode(25, OUTPUT); pinMode(33, OUTPUT); pinMode(13, OUTPUT);

    // All off
    digitalWrite(27, LOW); digitalWrite(26, LOW); analogWrite(14, 0);
    digitalWrite(25, LOW); digitalWrite(33, LOW); analogWrite(13, 0);

    Serial.println("=== BARE MINIMUM MOTOR TEST ===");
    Serial.println("Pins: LEFT=27,26,14  RIGHT=25,33,13");
    delay(2000);

    // ── TEST 1: LEFT motor alone ──────────────────────────────────────────────
    Serial.println("\n[TEST 1] LEFT motor forward (IN1=HIGH, IN2=LOW, ENA=150)");
    digitalWrite(27, HIGH);   // IN1 HIGH
    digitalWrite(26, LOW);    // IN2 LOW
    analogWrite(14, 150);     // ENA PWM
    delay(3000);
    // Stop
    analogWrite(14, 0); digitalWrite(27, LOW); digitalWrite(26, LOW);
    Serial.println("  stopped");
    delay(1000);

    // ── TEST 2: RIGHT motor alone ─────────────────────────────────────────────
    Serial.println("\n[TEST 2] RIGHT motor forward (IN3=HIGH, IN4=LOW, ENB=150)");
    digitalWrite(25, HIGH);   // IN3 HIGH
    digitalWrite(33, LOW);    // IN4 LOW
    analogWrite(13, 150);     // ENB PWM
    delay(3000);
    // Stop
    analogWrite(13, 0); digitalWrite(25, LOW); digitalWrite(33, LOW);
    Serial.println("  stopped");
    delay(1000);

    // ── TEST 3: BOTH motors ───────────────────────────────────────────────────
    Serial.println("\n[TEST 3] BOTH motors forward");
    digitalWrite(27, HIGH); digitalWrite(26, LOW); analogWrite(14, 150);
    digitalWrite(25, HIGH); digitalWrite(33, LOW); analogWrite(13, 150);
    delay(3000);
    // Stop all
    analogWrite(14, 0); analogWrite(13, 0);
    digitalWrite(27, LOW); digitalWrite(26, LOW);
    digitalWrite(25, LOW); digitalWrite(33, LOW);
    Serial.println("  stopped");

    Serial.println("\n=== AUTO TEST DONE ===");
    Serial.println("Commands: L=left  R=right  B=both  S=stop");
}

void loop() {
    if (!Serial.available()) return;
    char c = Serial.read();

    if (c == 'L' || c == 'l') {
        Serial.println("LEFT motor");
        analogWrite(13, 0); digitalWrite(25, LOW); digitalWrite(33, LOW);
        digitalWrite(27, HIGH); digitalWrite(26, LOW); analogWrite(14, 150);

    } else if (c == 'R' || c == 'r') {
        Serial.println("RIGHT motor");
        analogWrite(14, 0); digitalWrite(27, LOW); digitalWrite(26, LOW);
        digitalWrite(25, HIGH); digitalWrite(33, LOW); analogWrite(13, 150);

    } else if (c == 'B' || c == 'b') {
        Serial.println("BOTH motors");
        digitalWrite(27, HIGH); digitalWrite(26, LOW); analogWrite(14, 150);
        digitalWrite(25, HIGH); digitalWrite(33, LOW); analogWrite(13, 150);

    } else if (c == 'S' || c == 's') {
        Serial.println("STOP");
        analogWrite(14, 0); analogWrite(13, 0);
        digitalWrite(27, LOW); digitalWrite(26, LOW);
        digitalWrite(25, LOW); digitalWrite(33, LOW);
    }
}
