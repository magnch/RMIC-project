import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import requests
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

# --- CONFIG ---
BOT_IP = "192.168.1.108"
DEADZONE = 0.15

STREAM_URL = f"http://{BOT_IP}:81/stream"
SNAPSHOT_URL = f"http://{BOT_IP}/capture"
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "pose_landmarker_lite.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"

POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7),
    (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10),
    (11, 12),
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (29, 31),
    (24, 26), (26, 28), (28, 30), (30, 32),
]


def ensure_model() -> Path:
    if MODEL_PATH.exists():
        return MODEL_PATH

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Lade Pose-Modell herunter: {MODEL_URL}")

    with requests.get(MODEL_URL, timeout=20, stream=True) as response:
        response.raise_for_status()
        with open(MODEL_PATH, "wb") as model_file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    model_file.write(chunk)

    return MODEL_PATH


def open_stream() -> cv2.VideoCapture:
    cap = cv2.VideoCapture(STREAM_URL)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def fetch_snapshot_frame() -> np.ndarray | None:
    try:
        response = requests.get(SNAPSHOT_URL, timeout=0.6)
        response.raise_for_status()
        image_data = np.frombuffer(response.content, dtype=np.uint8)
        frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
        return frame
    except requests.RequestException:
        return None


def build_landmarker() -> vision.PoseLandmarker:
    model_path = ensure_model()
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def draw_pose(frame, landmarks) -> None:
    height, width = frame.shape[:2]
    points = []

    for landmark in landmarks:
        x = int(landmark.x * width)
        y = int(landmark.y * height)
        points.append((x, y))
        cv2.circle(frame, (x, y), 3, (0, 255, 0), -1)

    for start, end in POSE_CONNECTIONS:
        if start < len(points) and end < len(points):
            cv2.line(frame, points[start], points[end], (255, 180, 0), 2)


def main() -> None:
    landmarker = build_landmarker()

    cap = open_stream()
    consecutive_stream_failures = 0
    last_frame_ts = time.time()
    fps = 0.0

    print("Tracking gestartet. Nur Visualisierung aktiv (keine Fahrbefehle).")
    print(f"Primärer Stream: {STREAM_URL}")
    print(f"Fallback Snapshot: {SNAPSHOT_URL}")

    try:
        while True:
            now = time.time()
            dt = now - last_frame_ts
            if dt > 0:
                instant_fps = 1.0 / dt
                fps = (0.9 * fps) + (0.1 * instant_fps) if fps > 0 else instant_fps
            last_frame_ts = now

            if not cap.isOpened():
                cap.release()
                cap = open_stream()
                time.sleep(0.15)
                continue

            success, frame = cap.read()
            if not success or frame is None:
                consecutive_stream_failures += 1

                fallback_frame = fetch_snapshot_frame()
                if fallback_frame is not None:
                    frame = fallback_frame
                else:
                    if consecutive_stream_failures >= 3:
                        cap.release()
                        cap = open_stream()
                        consecutive_stream_failures = 0
                    time.sleep(0.06)
                    continue
            else:
                consecutive_stream_failures = 0

            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            result = landmarker.detect(mp_image)

            if result.pose_landmarks:
                landmarks = result.pose_landmarks[0]
                nose_x = landmarks[0].x
                error = nose_x - 0.5

                if error < -DEADZONE:
                    direction = "links"
                elif error > DEADZONE:
                    direction = "rechts"
                else:
                    direction = "mitte"

                draw_pose(frame, landmarks)
                status = f"POSE erkannt | nose_x={nose_x:.2f} | error={error:+.2f} | dir={direction}"
            else:
                status = "Keine Pose erkannt"

            cv2.putText(frame, status, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 220, 0), 2)

            cv2.imshow("AlphaBot AI Vision", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        landmarker.close()


if __name__ == "__main__":
    main()
