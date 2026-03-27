#include <Servo.h>

// Motor-Pins
const int IN1 = A0; const int IN2 = A1; const int ENA = 5;
const int IN3 = A2; const int IN4 = A3; const int ENB = 6;

// Ultrasonic sensor + servo
const int trigPin = 11; const int echoPin = 12;
Servo meinServo;
int aktuellerWinkel = 90;

// Motor ramp control
const int RAMP_STEP = 3;
const int RAMP_INTERVAL_MS = 20;
const int START_KICK_PWM = 130;
const int START_BOOST_MS = 45;
const int AUTO_REKICK_MAX_CMD_PWM = 60;
const int AUTO_REKICK_PWM = 90;
const int AUTO_REKICK_INTERVAL_MS = 650;
const int TURN_INNER_PERCENT = 45;   // 40 weniger support 
const int TURN_MIN_INNER_PWM = 55;

char motorDir = 'S';
int commandedPwm = 0;
int pwmTarget = 0;
int pwmCurrent = 0;
unsigned long boostUntil = 0;
unsigned long lastRampUpdate = 0;
unsigned long lastRekickAt = 0;

void applyDirection(char d);
void applyPwmByDirection(int pwm);
void updateMotorRamp();

void setup() {
  // Initialize motors
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT); pinMode(ENA, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT); pinMode(ENB, OUTPUT);
  
  // Initialize sensors
  pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
  
  meinServo.attach(9); // Servo on S1
  meinServo.write(aktuellerWinkel);
  
  Serial.begin(115200);
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    // Motor: M[Direction][Speed], e.g. MF200
    if (cmd.startsWith("M")) { 
      char dir = cmd[1];
      int speed = cmd.substring(2).toInt();
      executeMotor(dir, speed);
    } 
    // Servo: V[Angle], e.g. V120
    else if (cmd.startsWith("V")) { 
      aktuellerWinkel = cmd.substring(1).toInt();
      meinServo.write(aktuellerWinkel);
    }
  }

  updateMotorRamp();

  // Telemetry (send status back to the Mac every 300 ms)
  static unsigned long timer = 0;
  if (millis() - timer > 300) {
    Serial.print("D:"); Serial.print(get_dist());
    Serial.print("|V:"); Serial.println(aktuellerWinkel);
    timer = millis();
  }
}

void executeMotor(char d, int s) {
  int speed = constrain(s, 0, 255);

  if ((d != 'F' && d != 'B' && d != 'L' && d != 'R') || speed == 0) {
    motorDir = 'S';
    commandedPwm = 0;
    pwmCurrent = 0;
    pwmTarget = 0;
    boostUntil = 0;
    lastRekickAt = 0;
    applyDirection(motorDir);
    applyPwmByDirection(0);
    return;
  }

  motorDir = d;
  commandedPwm = speed;
  applyDirection(motorDir);

  // Hard start kick only when starting from standstill
  if (pwmCurrent == 0 && commandedPwm > 0 && commandedPwm < START_KICK_PWM && boostUntil == 0) {
    pwmCurrent = START_KICK_PWM;
    applyPwmByDirection(pwmCurrent);
    pwmTarget = START_KICK_PWM;
    boostUntil = millis() + START_BOOST_MS;
    lastRekickAt = millis();
  } else if (boostUntil == 0) {
    pwmTarget = commandedPwm;
  }
}

void applyDirection(char d) {
  if (d == 'F') {
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
  } else if (d == 'B') {
    digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);
    digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
  } else if (d == 'L') {
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
  } else if (d == 'R') {
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
  } else {
    digitalWrite(IN1, LOW);  digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, LOW);
  }
}

void applyPwmByDirection(int pwm) {
  if (motorDir == 'L') {
    int innerPwm = (pwm * TURN_INNER_PERCENT) / 100;
    if (pwm > 0 && innerPwm < TURN_MIN_INNER_PWM) innerPwm = TURN_MIN_INNER_PWM;
    if (innerPwm > pwm) innerPwm = pwm;
    analogWrite(ENA, innerPwm);
    analogWrite(ENB, pwm);
  } else if (motorDir == 'R') {
    int innerPwm = (pwm * TURN_INNER_PERCENT) / 100;
    if (pwm > 0 && innerPwm < TURN_MIN_INNER_PWM) innerPwm = TURN_MIN_INNER_PWM;
    if (innerPwm > pwm) innerPwm = pwm;
    analogWrite(ENA, pwm);
    analogWrite(ENB, innerPwm);
  } else if (motorDir == 'S') {
    analogWrite(ENA, 0);
    analogWrite(ENB, 0);
  } else {
    analogWrite(ENA, pwm);
    analogWrite(ENB, pwm);
  }
}

void updateMotorRamp() {
  unsigned long now = millis();

  if (boostUntil != 0 && now >= boostUntil) {
    boostUntil = 0;
    pwmTarget = commandedPwm;
  }

  // Periodic re-kick for low-speed commands to overcome motor stiction.
  if (
    boostUntil == 0 &&
    motorDir != 'S' &&
    commandedPwm > 0 &&
    commandedPwm <= AUTO_REKICK_MAX_CMD_PWM &&
    pwmCurrent <= (commandedPwm + 8) &&
    (now - lastRekickAt) >= AUTO_REKICK_INTERVAL_MS
  ) {
    pwmCurrent = AUTO_REKICK_PWM;
    applyPwmByDirection(pwmCurrent);
    lastRekickAt = now;
  }

  if (now - lastRampUpdate < RAMP_INTERVAL_MS) {
    return;
  }
  lastRampUpdate = now;

  if (pwmCurrent < pwmTarget) {
    pwmCurrent += RAMP_STEP;
    if (pwmCurrent > pwmTarget) pwmCurrent = pwmTarget;
  } else if (pwmCurrent > pwmTarget) {
    pwmCurrent -= RAMP_STEP;
    if (pwmCurrent < pwmTarget) pwmCurrent = pwmTarget;
  }

  applyPwmByDirection(pwmCurrent);
}

float get_dist() {
  digitalWrite(trigPin, LOW); delayMicroseconds(2);
  digitalWrite(trigPin, HIGH); delayMicroseconds(10); // 10us pulse
  digitalWrite(trigPin, LOW);
  return pulseIn(echoPin, HIGH) * 0.034 / 2.0; // Convert to cm
}