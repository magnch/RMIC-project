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

# Follow behavior
TURN_SPEED = 65
FORWARD_SPEED = 60
CENTER_DEADZONE = 0.12
DIST_NEAR = 0.22
DIST_FAR = 0.12

# Smoothing (0..1): higher = reacts faster
SMOOTH_ALPHA = 0.2

# Command rate limiting
CMD_MIN_INTERVAL_S = 0.1

STREAM_URL = f"http://{BOT_IP}:81/stream"
SNAPSHOT_URL = f"http://{BOT_IP}/capture"
CMD_URL = f"http://{BOT_IP}/cmd"
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


class BotController:
    def __init__(self) -> None:
        self.last_cmd = ""
        self.last_sent_at = 0.0

    def send(self, cmd: str, force: bool = False) -> bool:
        now = time.time()

        if not force:
            if cmd == self.last_cmd and (now - self.last_sent_at) < CMD_MIN_INTERVAL_S:
                return True

        try:
            response = requests.get(CMD_URL, params={"p": cmd}, timeout=0.15)
            if response.ok:
                self.last_cmd = cmd
                self.last_sent_at = now
                return True
        except requests.RequestException:
            return False

        return False


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


def smooth_value(current: float | None, new_value: float) -> float:
    if current is None:
        return new_value
    return (1.0 - SMOOTH_ALPHA) * current + SMOOTH_ALPHA * new_value


def compute_shoulder_width(landmarks) -> float | None:
    if len(landmarks) <= 12:
        return None

    left = landmarks[11]
    right = landmarks[12]
    dx = left.x - right.x
    dy = left.y - right.y
    width = (dx * dx + dy * dy) ** 0.5
    return width


def choose_command(error: float, shoulder_width: float) -> tuple[str, str]:
    if shoulder_width > DIST_NEAR:
        if error < -CENTER_DEADZONE:
            return f"ML{TURN_SPEED}", "zu nah -> links ausrichten"
        if error > CENTER_DEADZONE:
            return f"MR{TURN_SPEED}", "zu nah -> rechts ausrichten"
        return "MS", "zu nah -> stop"

    if shoulder_width < DIST_FAR:
        if error < -CENTER_DEADZONE:
            return f"ML{TURN_SPEED}", "zu weit -> links drehen"
        if error > CENTER_DEADZONE:
            return f"MR{TURN_SPEED}", "zu weit -> rechts drehen"
        return f"MF{FORWARD_SPEED}", "zu weit -> langsam vorwaerts"

    if error < -CENTER_DEADZONE:
        return f"ML{TURN_SPEED}", "ok dist -> links ausrichten"
    if error > CENTER_DEADZONE:
        return f"MR{TURN_SPEED}", "ok dist -> rechts ausrichten"
    return "MS", "ok dist + zentriert -> stop"


def main() -> None:
    landmarker = build_landmarker()
    bot = BotController()

    cap = open_stream()
    consecutive_stream_failures = 0
    last_frame_ts = time.time()
    fps = 0.0
    smoothed_nose_x = None
    smoothed_shoulder_w = None

    print("Tracking gestartet. Slow-Follow aktiv.")
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

            frame = cv2.rotate(frame, cv2.ROTATE_180)

            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            result = landmarker.detect(mp_image)

            cmd = "MS"
            state = "keine pose"

            if result.pose_landmarks:
                landmarks = result.pose_landmarks[0]
                nose_x = landmarks[0].x
                shoulder_w = compute_shoulder_width(landmarks)

                if shoulder_w is not None:
                    smoothed_nose_x = smooth_value(smoothed_nose_x, nose_x)
                    smoothed_shoulder_w = smooth_value(smoothed_shoulder_w, shoulder_w)
                    error = smoothed_nose_x - 0.5
                    cmd, state = choose_command(error, smoothed_shoulder_w)
                    status = (
                        f"POSE | nose_x={smoothed_nose_x:.2f} | err={error:+.2f} "
                        f"| shoulder={smoothed_shoulder_w:.3f}"
                    )
                else:
                    status = "Pose unvollstaendig (Schulter fehlt)"
                    state = "ungueltige pose"
                    cmd = "MS"

                draw_pose(frame, landmarks)
            else:
                cmd = "MS"
                state = "keine pose -> stop"
                status = "Keine Pose erkannt"

            bot.send(cmd)

            cv2.putText(frame, status, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 220, 0), 2)
            cv2.putText(frame, f"STATE: {state}", (10, 101), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (120, 255, 255), 2)
            cv2.putText(frame, f"CMD: {cmd}", (10, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (120, 255, 255), 2)

            cv2.imshow("AlphaBot AI Vision", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        bot.send("MS", force=True)
        cap.release()
        cv2.destroyAllWindows()
        landmarker.close()


if __name__ == "__main__":
    main()
