import json
import time
from threading import Lock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import requests
from ultralytics import YOLO

# --- CONFIG ---
BOT_IP = "172.20.10.6"

# Forward-priority follow behavior
FORWARD_SPEED = 60
TURN_SPEED = 50

# Sensitive center tuning (smaller deadzone = more sensitive)
CENTER_TARGET_X = 0.5
STEER_DEADZONE = 0.06
STEER_HARDZONE = 0.14

# Smoothing (0..1): higher = reacts faster
SMOOTH_ALPHA = 0.35

# Command rate limiting
CMD_MIN_INTERVAL_S = 0.05
TRACKING_SEND_MOTOR_COMMANDS = False

# Video source mode: stream-only
VIDEO_SOURCE_MODE = "stream"
NO_FRAME_LOG_INTERVAL_S = 3.0
STREAM_CONNECT_TIMEOUT_S = 2.0
STREAM_READ_TIMEOUT_S = 8.0

# YOLO config
YOLO_MODEL_NAME = "yolov8n.pt"
YOLO_PERSON_CLASS_ID = 0
YOLO_CONF_THRESHOLD = 0.35
YOLO_IMAGE_SIZE = 320
YOLO_INFER_EVERY_N_FRAMES = 1
YOLO_MAX_STALE_FRAMES = 1

# Local relay server for Android/web consumers (no Firebase needed)
RELAY_HOST = "0.0.0.0"
RELAY_PORT = 8090
RELAY_PATH = "/frame.jpg"
RELAY_MJPEG_PATH = "/stream.mjpg"
RELAY_STATUS_PATH = "/status.json"
RELAY_JPEG_QUALITY = 70

STREAM_URL = f"http://{BOT_IP}:81/stream"
CMD_URL = f"http://{BOT_IP}/cmd"

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

        byte_iter = self.byte_iter
        if byte_iter is None:
            return None

        try:
            for chunk in byte_iter:
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


def build_detector() -> YOLO:
    return YOLO(YOLO_MODEL_NAME)


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


def smooth_value(current: float | None, new_value: float) -> float:
    if current is None:
        return new_value
    return (1.0 - SMOOTH_ALPHA) * current + SMOOTH_ALPHA * new_value


def choose_forward_priority_command(error: float, last_turn_dir: int) -> tuple[str, str, int]:
    abs_error = abs(error)

    if abs_error <= STEER_DEADZONE:
        return f"MF{FORWARD_SPEED}", "zentriert -> vorwaerts", 0

    turn_dir = -1 if error < 0 else 1
    if turn_dir < 0:
        if turn_dir != last_turn_dir:
            return f"ML{TURN_SPEED}", "richtungswechsel -> links", turn_dir
        return f"ML{TURN_SPEED}", "korrigiere links", turn_dir
    if turn_dir != last_turn_dir:
        return f"MR{TURN_SPEED}", "richtungswechsel -> rechts", turn_dir
    return f"MR{TURN_SPEED}", "korrigiere rechts", turn_dir


def pick_person_box(result) -> tuple[bool, tuple[int, int, int, int] | None, float]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return False, None, 0.0

    confs = boxes.conf.detach().cpu().numpy()
    classes = boxes.cls.detach().cpu().numpy().astype(int)

    person_indices = np.where(classes == YOLO_PERSON_CLASS_ID)[0]
    if person_indices.size == 0:
        return False, None, 0.0

    best_rel_idx = int(np.argmax(confs[person_indices]))
    best_idx = int(person_indices[best_rel_idx])
    best_conf = float(confs[best_idx])

    if best_conf < YOLO_CONF_THRESHOLD:
        return False, None, best_conf

    xyxy = boxes.xyxy[best_idx].detach().cpu().numpy()
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    return True, (x1, y1, x2, y2), best_conf


def draw_target(frame, box: tuple[int, int, int, int], conf: float) -> None:
    x1, y1, x2, y2 = box
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(
        frame,
        f"person {conf:.2f}",
        (x1, max(20, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
    )


def main() -> None:
    detector = build_detector()
    bot = BotController()
    relay_server = start_relay_server()
    mjpeg_reader = MjpegStreamReader(STREAM_URL)

    last_frame_ts = time.time()
    fps = 0.0
    smoothed_target_x = None
    last_no_frame_log_at = 0.0
    frame_count = 0
    cached_has_person = False
    cached_box = None
    cached_conf = 0.0
    cached_stale_frames = YOLO_MAX_STALE_FRAMES + 1
    last_turn_dir = 0

    print("Tracking gestartet. YOLO Forward-priority Tracking aktiv.")
    print(f"YOLO-Modell: {YOLO_MODEL_NAME}")
    print(f"Video mode: {VIDEO_SOURCE_MODE}")
    print(f"Primärer Stream: {STREAM_URL}")
    print(f"Relay: http://127.0.0.1:{RELAY_PORT}{RELAY_PATH}")
    print(f"Relay MJPEG: http://127.0.0.1:{RELAY_PORT}{RELAY_MJPEG_PATH}")
    print(f"Relay Status: http://127.0.0.1:{RELAY_PORT}{RELAY_STATUS_PATH}")
    print(f"Motorsteuerung aktiv: {TRACKING_SEND_MOTOR_COMMANDS}")

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
                    print("[tracking_yolo] Kein Frame von /stream -> reconnect")
                    last_no_frame_log_at = now
                mjpeg_reader.close()
                time.sleep(0.12)
                continue

            frame_count += 1
            should_infer = (
                cached_stale_frames > YOLO_MAX_STALE_FRAMES
                or (frame_count % YOLO_INFER_EVERY_N_FRAMES == 0)
            )

            if should_infer:
                yolo_result = detector(
                    frame,
                    verbose=False,
                    classes=[YOLO_PERSON_CLASS_ID],
                    conf=YOLO_CONF_THRESHOLD,
                    imgsz=YOLO_IMAGE_SIZE,
                )[0]
                has_person, box, conf = pick_person_box(yolo_result)
                cached_has_person = has_person
                cached_box = box
                cached_conf = conf
                cached_stale_frames = 0
            else:
                cached_stale_frames += 1

            cmd = "MS"
            has_person = cached_has_person and cached_stale_frames <= YOLO_MAX_STALE_FRAMES
            box = cached_box
            conf = cached_conf

            if has_person and box is not None:
                x1, _, x2, _ = box
                frame_w = frame.shape[1]
                target_x = ((x1 + x2) * 0.5) / frame_w

                smoothed_target_x = smooth_value(smoothed_target_x, target_x)
                error = smoothed_target_x - CENTER_TARGET_X
                cmd, state_text, last_turn_dir = choose_forward_priority_command(error, last_turn_dir)
                draw_target(frame, box, conf)
                if not should_infer:
                    state_text = f"{state_text} (cached)"
            else:
                cmd = "MS"
                state_text = "keine person -> stop"
                last_turn_dir = 0

            if TRACKING_SEND_MOTOR_COMMANDS:
                bot.send(cmd)

            update_relay_status(
                pose=has_person,
                fps=fps,
                state=state_text,
                cmd=cmd,
            )

            update_relay_frame(frame)

            cv2.imshow("AlphaBot AI Vision (YOLO)", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        mjpeg_reader.close()
        relay_server.shutdown()
        relay_server.server_close()
        if TRACKING_SEND_MOTOR_COMMANDS:
            bot.send("MS", force=True)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()