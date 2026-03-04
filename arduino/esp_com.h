#pragma once
#include <Arduino.h>

// ESP commands
enum esp_cmd {
    CMD_NONE,
    CMD_STOP = 'S',
    CMD_FORWARD = 'F',
    CMD_BACKWARD = 'B',
    CMD_LEFT = 'L',
    CMD_RIGHT = 'R',
    CMD_SET_SPEED = 'V'
};

// Function to read command from serial input
enum esp_cmd get_command(uint8_t &speed);