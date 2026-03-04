#pragma once
#include <Arduino.h>

// Motor control pins
#define IN1 A0
#define IN2 A1
#define IN3 A2
#define IN4 A3
// Speed control pins (PWM)
#define ENA 5
#define ENB 6

// Motor control functions
void motor_init(void);
void motor_forward(uint8_t speed);
void motor_backward(uint8_t speed);
void motor_turn_left(uint8_t speed);
void motor_turn_right(uint8_t speed);
void motor_stop();