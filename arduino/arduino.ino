

void setup() {
  // Initialize motor control
  motor_init();

  Serial.begin(115200);

}

void loop() {
    Serial.println("Heartbeat");
    delay(1000);
}