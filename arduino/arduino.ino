#include <Servo.h>

// Motor pins
const int IN1 = A0; const int IN2 = A1; const int ENA = 5;
const int IN3 = A2; const int IN4 = A3; const int ENB = 6;

// Ultrasonic sensor and servo
const int trigPin = 11; const int echoPin = 12;
Servo meinServo;
int aktuellerWinkel = 90;

// Motor ramp control
const int RAMP_STEP = 3;  // Larger = faster ramp-up/down, smaller = smoother but slower response.
const int RAMP_INTERVAL_MS = 20; // Smaller = more frequent updates and quicker response, larger = slower.
const int START_KICK_PWM = 90;
const int START_BOOST_MS = 20;
const bool ENABLE_START_KICK = true;

const int AUTO_REKICK_MAX_CMD_PWM = 50; // Threshold

const int AUTO_REKICK_PWM = 90; // PWM value
const int AUTO_REKICK_INTERVAL_MS = 650; // Interval in milliseconds
const bool ENABLE_AUTO_REKICK = false;

const int TURN_INNER_PERCENT = 88;  // follow steering: both wheels forward, inner wheel slower
const int TURN_MIN_INNER_PWM = 60;  // keep inner wheel moving for stable curved follow turns

const unsigned long COMMAND_WATCHDOG_MS = 10000;
const bool ENABLE_COMMAND_WATCHDOG = false;

const uint8_t STOP_REASON_NONE = 0;
const uint8_t STOP_REASON_CMD_ZERO = 1;
const uint8_t STOP_REASON_CMD_INVALID = 2;
const uint8_t STOP_REASON_WATCHDOG = 3;

char motorDir = 'S';
int commandedPwm = 0;
int pwmTarget = 0;
int pwmCurrent = 0;
unsigned long boostUntil = 0;
unsigned long lastRampUpdate = 0;
unsigned long lastRekickAt = 0;
unsigned long lastMotorCommandAt = 0;
char lastRxDir = 'S';
int lastRxSpeed = 0;
unsigned long rxCount = 0;
uint8_t lastStopReason = STOP_REASON_NONE;
unsigned long watchdogStopCount = 0;

void applyDirection(char d);
void applyPwmByDirection(int pwm);
void updateMotorRamp();
void stopIfCommandTimedOut();
void hardStop(uint8_t reason);
const char* stopReasonToText(uint8_t reason);

void setup() {
  // Initialize motors
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT); pinMode(ENA, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT); pinMode(ENB, OUTPUT);
  
  // Initialize sensors
  pinMode(trigPin, OUTPUT); pinMode(echoPin, INPUT);
  
  meinServo.attach(9); // Servo on S1
  meinServo.write(aktuellerWinkel);
  
  Serial.begin(115200);
  Serial.setTimeout(20);
  lastMotorCommandAt = millis();
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    // Motor: M[Direction][Speed], e.g. MF200
    if (cmd.startsWith("M")) { 
      if (cmd.length() < 2) {
        hardStop(STOP_REASON_CMD_INVALID);
      } else {
        char dir = cmd[1];
        int speed = cmd.substring(2).toInt();
        executeMotor(dir, speed);
      }
    } 
    // Servo: V[Angle], e.g. V120
    else if (cmd.startsWith("V")) { 
      aktuellerWinkel = cmd.substring(1).toInt();
      meinServo.write(aktuellerWinkel);
    }
  }

  stopIfCommandTimedOut();
  updateMotorRamp();

  // Telemetry (send status back to the host every 300 ms)
  static unsigned long timer = 0;
  if (millis() - timer > 300) {
    Serial.print("D:"); Serial.print(get_dist());
    Serial.print("|V:"); Serial.print(aktuellerWinkel);
    Serial.print("|RX:"); Serial.print(lastRxDir); Serial.print(lastRxSpeed);
    Serial.print("|CNT:"); Serial.print(rxCount);
    Serial.print("|MD:"); Serial.print(motorDir); Serial.print(commandedPwm);
    Serial.print("|PWM:"); Serial.print(pwmCurrent); Serial.print('/'); Serial.print(pwmTarget);
    Serial.print("|AGE:"); Serial.print(millis() - lastMotorCommandAt);
    Serial.print("|STOP:"); Serial.print(stopReasonToText(lastStopReason));
    Serial.print("|WD:"); Serial.println(watchdogStopCount);
    timer = millis();
  }
}

void executeMotor(char d, int s) {
  int speed = constrain(s, 0, 255);
  lastMotorCommandAt = millis();
  lastRxDir = d;
  lastRxSpeed = speed;
  rxCount++;

  if ((d != 'F' && d != 'B' && d != 'L' && d != 'R' && d != 'G' && d != 'H') || speed == 0) {
    if (speed == 0) {
      hardStop(STOP_REASON_CMD_ZERO);
    } else {
      hardStop(STOP_REASON_CMD_INVALID);
    }
    return;
  }

  motorDir = d;
  commandedPwm = speed;
  applyDirection(motorDir);

  // Hard start kick only when starting from standstill
  if (ENABLE_START_KICK && pwmCurrent == 0 && commandedPwm > 0 && commandedPwm < START_KICK_PWM && boostUntil == 0) {
    pwmCurrent = START_KICK_PWM;
    applyPwmByDirection(pwmCurrent);
    pwmTarget = START_KICK_PWM;
    boostUntil = millis() + START_BOOST_MS;
    lastRekickAt = millis();
  } else if (boostUntil == 0) {
    pwmTarget = commandedPwm;
  }
}

void hardStop(uint8_t reason) {
  motorDir = 'S';
  commandedPwm = 0;
  pwmCurrent = 0;
  pwmTarget = 0;
  boostUntil = 0;
  lastRekickAt = 0;
  lastStopReason = reason;
  applyDirection(motorDir);
  applyPwmByDirection(0);
}

void stopIfCommandTimedOut() {
  if (!ENABLE_COMMAND_WATCHDOG) {
    return;
  }

  if (motorDir == 'S') {
    return;
  }

  if (millis() - lastMotorCommandAt <= COMMAND_WATCHDOG_MS) {
    return;
  }

  watchdogStopCount++;
  hardStop(STOP_REASON_WATCHDOG);
}

const char* stopReasonToText(uint8_t reason) {
  if (reason == STOP_REASON_CMD_ZERO) return "cmd0";
  if (reason == STOP_REASON_CMD_INVALID) return "invalid";
  if (reason == STOP_REASON_WATCHDOG) return "watchdog";
  return "none";
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
  } else if (d == 'G') {
    // Seek left one-wheel steering: both wheels forward, left wheel can be set to 0 PWM.
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
  } else if (d == 'H') {
    // Seek right one-wheel steering: both wheels forward, right wheel can be set to 0 PWM.
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
  } else if (motorDir == 'G') {
    analogWrite(ENA, 0);
    analogWrite(ENB, pwm);
  } else if (motorDir == 'H') {
    analogWrite(ENA, pwm);
    analogWrite(ENB, 0);
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
    ENABLE_AUTO_REKICK &&
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
  digitalWrite(trigPin, HIGH); delayMicroseconds(10); // 10 us pulse
  digitalWrite(trigPin, LOW);
  return pulseIn(echoPin, HIGH) * 0.034 / 2.0; // Convert to centimeters
}