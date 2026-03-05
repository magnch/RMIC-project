#pragma once
#include <Arduino.h>

// ESP commands
enum esp_cmd {
    CMD_NONE,
    CMD_MODE_IDLE = '0',
    CMD_MODE_SENTRY = '1',
    CMD_MODE_STANDBY = '2',
    CMD_MOTOR_STOP = 'S',
    CMD_MOTOR_FORWARD = 'F',
    CMD_MOTOR_BACKWARD = 'B',
    CMD_MOTOR_LEFT = 'L',
    CMD_MOTOR_RIGHT = 'R',
    CMD_MOTOR_SET_SPEED = 'V'
};

// Function to read command from serial input
enum esp_cmd get_command(uint8_t &speed);