import time
import json
from pathlib import Path
from threading import Lock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import mediapipe as mp
import numpy as np
import requests
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

# --- CONFIG ---
# BOT_IP = "192.168.1.108"
BOT_IP = "10.104.31.108"

# Forward-priority follow behavior
FORWARD_SPEED = 60
TURN_SPEED = 50

# Sensitive center tuning (smaller deadzone = more sensitive)
CENTER_TARGET_X = 0.5
STEER_DEADZONE = 0.12
STEER_HARDZONE = 0.18

# Steering pulse cadence while still prioritizing forward movement
STEER_PULSE_EVERY_SOFT = 7
STEER_PULSE_EVERY_HARD = 4

# Smoothing (0..1): higher = reacts faster
SMOOTH_ALPHA = 0.2

# Command rate limiting
CMD_MIN_INTERVAL_S = 0.1
TRACKING_SEND_MOTOR_COMMANDS = False

# Video source mode: stream-only (requested)
VIDEO_SOURCE_MODE = "stream"
NO_FRAME_LOG_INTERVAL_S = 3.0
STREAM_CONNECT_TIMEOUT_S = 2.0
STREAM_READ_TIMEOUT_S = 8.0

# Local relay server for Android/web consumers (no Firebase needed)
RELAY_HOST = "0.0.0.0"
RELAY_PORT = 8090
RELAY_PATH = "/frame.jpg"
RELAY_MJPEG_PATH = "/stream.mjpg"
RELAY_STATUS_PATH = "/status.json"
RELAY_JPEG_QUALITY = 70

STREAM_URL = f"http://{BOT_IP}:81/stream"
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

_LATEST_FRAME_JPEG = None
_LATEST_FRAME_LOCK = Lock()
_LATEST_STATUS = {
    "pose": False,
    "fps": 0.0,
    "state": "init",
    "cmd": "MS",
}
_LATEST_STATUS_LOCK = Lock()


class RelayHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]

        if route == RELAY_MJPEG_PATH:
            self.serve_mjpeg_stream()
            return

        if route == RELAY_STATUS_PATH:
            self.serve_status_json()
            return

        if route != RELAY_PATH:
            self.send_response(404)
            self.end_headers()
            return

        with _LATEST_FRAME_LOCK:
            frame_bytes = _LATEST_FRAME_JPEG

        if frame_bytes is None:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"no frame yet")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame_bytes)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(frame_bytes)

    def serve_status_json(self):
        with _LATEST_STATUS_LOCK:
            payload = dict(_LATEST_STATUS)

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def serve_mjpeg_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()

        try:
            while True:
                with _LATEST_FRAME_LOCK:
                    frame_bytes = _LATEST_FRAME_JPEG

                if frame_bytes is None:
                    time.sleep(0.05)
                    continue

                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame_bytes)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame_bytes)
                self.wfile.write(b"\r\n")
                time.sleep(0.08)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            return

    def log_message(self, format, *args):
        return


def start_relay_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((RELAY_HOST, RELAY_PORT), RelayHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def update_relay_frame(frame) -> None:
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), RELAY_JPEG_QUALITY],
    )
    if not ok:
        return

    frame_bytes = encoded.tobytes()
    with _LATEST_FRAME_LOCK:
        global _LATEST_FRAME_JPEG
        _LATEST_FRAME_JPEG = frame_bytes


def update_relay_status(*, pose: bool, fps: float, state: str, cmd: str) -> None:
    with _LATEST_STATUS_LOCK:
        _LATEST_STATUS["pose"] = pose
        _LATEST_STATUS["fps"] = round(float(fps), 1)
        _LATEST_STATUS["state"] = state
        _LATEST_STATUS["cmd"] = cmd


def ensure_model() -> Path:
    if MODEL_PATH.exists():
        return MODEL_PATH

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading pose model: {MODEL_URL}")

    with requests.get(MODEL_URL, timeout=20, stream=True) as response:
        response.raise_for_status()
        with open(MODEL_PATH, "wb") as model_file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    model_file.write(chunk)

    return MODEL_PATH


class MjpegStreamReader:
    def __init__(self, url: str):
        self.url = url
        self.response = None
        self.byte_iter = None
        self.buffer = bytearray()

    def connect(self) -> bool:
        self.close()
        try:
            self.response = requests.get(
                self.url,
                stream=True,
                timeout=(STREAM_CONNECT_TIMEOUT_S, STREAM_READ_TIMEOUT_S),
            )
            self.response.raise_for_status()
            self.byte_iter = self.response.iter_content(chunk_size=4096)
            self.buffer.clear()
            return True
        except requests.RequestException:
            self.close()
            return False

    def read_frame(self) -> np.ndarray | None:
        if self.byte_iter is None:
            if not self.connect():
                return None

        try:
            for chunk in self.byte_iter:
                if not chunk:
                    continue

                self.buffer.extend(chunk)

                start = self.buffer.find(b"\xff\xd8")
                end = self.buffer.find(b"\xff\xd9", start + 2 if start != -1 else 0)

                if start != -1 and end != -1:
                    jpeg = bytes(self.buffer[start:end + 2])
                    del self.buffer[:end + 2]
                    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return frame

                if len(self.buffer) > 2_000_000:
                    self.buffer.clear()
                    break

            return None
        except requests.RequestException:
            self.close()
            return None
        except Exception:
            self.close()
            return None

    def close(self) -> None:
        if self.response is not None:
            try:
                self.response.close()
            except Exception:
                pass
        self.response = None
        self.byte_iter = None
        self.buffer.clear()


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


def choose_forward_priority_command(error: float) -> tuple[str, str]:
    abs_error = abs(error)

    if abs_error <= STEER_DEADZONE:
        return f"MF{FORWARD_SPEED}", "centered -> forward"

    if error < 0:
        return f"ML{TURN_SPEED}", "correct left"
    return f"MR{TURN_SPEED}", "correct right"


def main() -> None:
    landmarker = build_landmarker()
    bot = BotController()
    relay_server = start_relay_server()
    mjpeg_reader = MjpegStreamReader(STREAM_URL)

    last_frame_ts = time.time()
    fps = 0.0
    pose_tick = 0
    smoothed_nose_x = None
    last_no_frame_log_at = 0.0

    print("Tracking started. Forward-priority tracking active.")
    print(f"Video mode: {VIDEO_SOURCE_MODE}")
    print(f"Primary stream: {STREAM_URL}")
    print(f"Relay: http://127.0.0.1:{RELAY_PORT}{RELAY_PATH}")
    print(f"Relay MJPEG: http://127.0.0.1:{RELAY_PORT}{RELAY_MJPEG_PATH}")
    print(f"Relay Status: http://127.0.0.1:{RELAY_PORT}{RELAY_STATUS_PATH}")
    print(f"Motor control enabled: {TRACKING_SEND_MOTOR_COMMANDS}")

    try:
        while True:
            now = time.time()
            dt = now - last_frame_ts
            if dt > 0:
                instant_fps = 1.0 / dt
                fps = (0.9 * fps) + (0.1 * instant_fps) if fps > 0 else instant_fps
            last_frame_ts = now

            frame = mjpeg_reader.read_frame()
            if frame is None:
                update_relay_status(
                    pose=False,
                    fps=fps,
                    state="no_frame_reconnect",
                    cmd="MS",
                )
                if (now - last_no_frame_log_at) >= NO_FRAME_LOG_INTERVAL_S:
                    print("[tracking] No frame from /stream -> reconnect")
                    last_no_frame_log_at = now
                mjpeg_reader.close()
                time.sleep(0.12)
                continue

            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            result = landmarker.detect(mp_image)

            pose_detected = bool(result.pose_landmarks)

            cmd = "MS"

            if pose_detected:
                landmarks = result.pose_landmarks[0]
                nose_x = landmarks[0].x
                smoothed_nose_x = smooth_value(smoothed_nose_x, nose_x)
                error = smoothed_nose_x - CENTER_TARGET_X
                pose_tick += 1

                cmd, state_text = choose_forward_priority_command(error)

                draw_pose(frame, landmarks)
            else:
                smoothed_nose_x = None  # Reset tracking smoothing when completely lost
                cmd = "MS"
                state_text = "no pose -> stop"

            if TRACKING_SEND_MOTOR_COMMANDS:
                bot.send(cmd)

            update_relay_status(
                pose=pose_detected,
                fps=fps,
                state=state_text,
                cmd=cmd,
            )

            update_relay_frame(frame)

            cv2.imshow("AlphaBot AI Vision", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        mjpeg_reader.close()
        relay_server.shutdown()
        relay_server.server_close()
        if TRACKING_SEND_MOTOR_COMMANDS:
            bot.send("MS", force=True)
        cv2.destroyAllWindows()
        landmarker.close()


if __name__ == "__main__":
    main()
