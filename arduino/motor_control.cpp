#include "motor_control.h"


void motor_init() {
  // Set motor control pins as outputs
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  
  // Set speed control pins as outputs
  pinMode(ENA, OUTPUT);
  pinMode(ENB, OUTPUT);
}

void motor_forward(uint8_t speed) {
  // Set motor direction to forward
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
  
  // Set motor speed
  analogWrite(ENA, speed);
  analogWrite(ENB, speed);
}

void motor_backward(uint8_t speed) {
  // Set motor direction to backward
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
  
  // Set motor speed
  analogWrite(ENA, speed);
  analogWrite(ENB, speed);
}

void motor_turn_left(uint8_t speed) {
  // Set motor direction to turn left
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
  
  // Set motor speed
  analogWrite(ENA, speed);
  analogWrite(ENB, speed);
}

void motor_turn_right(uint8_t speed) {
  // Set motor direction to turn right
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
  
  // Set motor speed
  analogWrite(ENA, speed);
  analogWrite(ENB, speed);
}

void motor_stop() {
  // Stop the motors
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
  
  // Set speed to zero
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
}