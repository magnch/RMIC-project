#include "motor_control.h"
#include "esp_com.h"

enum mode {
    MODE_IDLE,
    MODE_SENTRY,
    MODE_STANDBY
};

void setup() {
  // Initialize motor control
  motor_init();

  Serial.begin(115200);
  Serial.println("Initialization done!");

}

enum esp_cmd current_command = CMD_NONE;
enum mode current_mode = MODE_IDLE;
uint8_t speed = 255; // Default speed (full speed)

void loop() {
    current_command = get_command(speed);
    Serial.println(current_command);
    delay(1000);
    switch(current_mode) {
        case MODE_IDLE:
            Serial.println("Idling...");
            break;
        case MODE_SENTRY:
            // Logic for autonomous driving
            break;
        case MODE_STANDBY:
            // Listen to commands from ESP32
            switch (current_command) {
                case CMD_MOTOR_FORWARD:
                    motor_forward(speed);
                    break;
                case CMD_MOTOR_BACKWARD:
                    motor_backward(speed);
                    break;
                case CMD_MOTOR_LEFT:
                    motor_turn_left(speed);
                    break;
                case CMD_MOTOR_RIGHT:
                    motor_turn_right(speed);
                    break;
                case CMD_MOTOR_STOP:
                    motor_stop(); // Stop the motors
                    break;
                case CMD_MOTOR_SET_SPEED:
                    // Speed is already updated in get_command, no need to do anything here
                    break;
                default:
                    // No command or unrecognized command, do nothing
                    break;
            }
    }
}
