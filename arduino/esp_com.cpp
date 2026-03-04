#include "esp_com.h"


enum esp_cmd  get_command(uint8_t &speed) {
    if (Serial.available() > 0) {
        enum esp_cmd cmd = Serial.read();
        if (cmd == CMD_SET_SPEED) {
            // Read the next byte for speed value
            while (Serial.available() == 0); // Wait for the speed byte
            speed = Serial.read();
            // You can store or use the speed value as needed
        }
        return cmd;
    }
    return CMD_NONE; // Default to none if no command is available
}
