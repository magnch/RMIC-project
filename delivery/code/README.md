# Security Bot
Autonomous Person Tracking and Patrol Monitoring

MEEC - Redes Moveis e Internet das Coisas (2025/2026)

## Project Overview
Security Bot is an autonomous mobile robot based on the AlphaBot platform.
It combines onboard sensing, wireless vision streaming, and server-side machine
learning to support security monitoring tasks.

The robot supports app-controlled mode profiles:
- IDLE: robot remains stopped.
- PATROL ONLY: robot patrols while using obstacle awareness.
- FOLLOW ONLY: robot follows a detected person.
- PATROL + FOLLOW: robot patrols and switches to follow behavior when a person is detected.

## Architecture Summary
The system is split into hardware control, perception, and user interaction:

- Vision and ML pipeline:
	ESP32-CAM streams video over Wi-Fi to a PC server, where the tracking and
	detection models run.
- Navigation and safety:
	Ultrasonic sensing supports obstacle awareness and safer movement.
- Motion and communications:
	ESP32 bridges camera/control data, while Arduino handles motor and servo control.
- Remote interface:
	A mobile app provides telemetry visualization and manual controls.

## Main Features
- Real-time person tracking.
- Person detection and status reporting.
- Obstacle-aware movement.
- Remote monitoring and control.

## Repository Structure
- `android-app/`: Android mobile application.
- `esp32/`: ESP32 firmware.
- `arduino/`: Arduino-side firmware and control logic.
- `python/`: PC-side scripts included in this submission (`patrol.py` and `tracking_yolo.py`).
- `yolov8n.pt`: model weights used by the tracking pipeline.

## Quick Start
Use the components according to your role (mobile app, embedded, or ML/server):

1. Flash firmware from `esp32/` and/or `arduino/` to the target boards.
2. Configure and run `python/patrol.py` and/or `python/tracking_yolo.py` on the PC/server.
3. Build and run the Android application from `android-app/`.
4. Ensure network connectivity between robot, server, and mobile app.

## Notes
- This repository contains multiple subsystems that must be configured together.
- Hardware availability and correct network setup are required for full testing.

## Team
Group 01 - MEEC 2025/2026
