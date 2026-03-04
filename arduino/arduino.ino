#include "motor_control.h"
#include "esp_com.h"


void setup() {
  // Initialize motor control
  motor_init();

  Serial.begin(115200);
  Serial.println("Initialization done!");

}

enum esp_cmd current_command = CMD_NONE;
uint8_t speed = 255; // Default speed (full speed)

void loop() {
    current_command = get_command(speed);
    Serial.println(current_command);
    delay(1000);
    switch (current_command) {
        case CMD_FORWARD:
            motor_forward(speed);
            break;
        case CMD_BACKWARD:
            motor_backward(speed);
            break;
        case CMD_LEFT:
            motor_turn_left(speed);
            break;
        case CMD_RIGHT:
            motor_turn_right(speed);
            break;
        case CMD_STOP:
            motor_stop(); // Stop the motors
            break;
        case CMD_SET_SPEED:
            // Speed is already updated in get_command, no need to do anything here
            break;
        default:
            // No command or unrecognized command, do nothing
            break;
    }
}
