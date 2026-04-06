# Security Bot 🤖🔐  
**Autonomous Person Tracking & Intruder Detection**  
MEEC – Redes Móveis e Internet das Coisas (2025/2026)

## Overview
Security Bot is an autonomous mobile robot built on the AlphaBot platform for intelligent security assistance. It operates in two modes:
- **Following Mode** – Tracks and follows a designated person.
- **Sentry Mode** – Detects and reports unauthorized intruders.

## System Architecture
- **Vision & ML:** ESP32-CAM streams video via WiFi to a PC server where a Machine Learning model performs object detection and tracking.
- **Navigation & Safety:** Ultrasonic sensor for obstacle avoidance; ESP32-C6 handles motor control and cloud communication.
- **Connectivity:** Real-time telemetry and manual controls via a Mobile App connected to a Firebase/PHP backend.

## Features
- Real-time person tracking  
- Intruder detection with cloud logging  
- Obstacle avoidance  
- Remote monitoring and control  

## Team
Group 01 – MEEC 2025/2026
