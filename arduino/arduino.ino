

void setup() {
  // Initialize motor control
  motor_init();

  Serial.begin(115200);

}

enum esp_cmd current_command = CMD_NONE;
uint8_t speed = 255; // Default speed (full speed)

void loop() {
    current_command = get_command();
    Serial.println(current_command);
    switch (current_command) {
        case CMD_FORWARD:
            motor_forward(speed); // Use the stored speed value
            break;
        case CMD_LEFT:
            motor_turn_left(speed); // Use the stored speed value
            break;
        case CMD_RIGHT:
            motor_turn_right(speed); // Use the stored speed value
            break;
        case CMD_STOP:
            motor_stop(); // Stop the motors
            break;
        default:
            // No command or unrecognized command, do nothing
            break;
    }
}