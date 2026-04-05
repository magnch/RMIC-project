import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import requests


@dataclass
class PatrolConfig:
    bot_ip: str = "172.20.10.6"

    obstacle_threshold_cm: float = 20.0
    forward_speed: int = 95
    turn_speed: int = 120
    reverse_speed: int = 85

    reverse_time_s: float = 0.60
    stop_before_turn_s: float = 0.08
    stop_after_reverse_s: float = 0.08
    turn_135_time_s: float = 0.95

    pose_hold_seconds: float = 3.0
    refresh_hold_on_continuous_pose: bool = False

    bot_status_timeout_s: float = 0.22
    cmd_timeout_s: float = 0.20
    loop_sleep_s: float = 0.06
    cmd_min_interval_s: float = 0.10

    tracking_status_url: str = "http://127.0.0.1:8090/status.json"
    tracking_status_timeout_s: float = 0.20
    tracking_backend: str = "yolo"  # "mediapipe" or "yolo"
    tracking_autostart: bool = True

    app_status_host: str = "0.0.0.0"
    app_status_port: int = 8091


APP_STATUS_PATH = "/status.json"
FIREBASE_DB_URL = "https://iot-alarm-app-b4b9c-default-rtdb.europe-west1.firebasedatabase.app"
FIREBASE_DISPLAY_BASE_PATH = "bots/alphabot/app_display"
FIREBASE_CONTROL_MODE_PATH = "bots/alphabot/app_control/mode_profile"
FIREBASE_WRITE_INTERVAL_S = 0.45
FIREBASE_CONTROL_READ_INTERVAL_S = 0.35

MODE_IDLE = "IDLE"
MODE_PATROL_ONLY = "PATROL_ONLY"
MODE_FOLLOW_ONLY = "FOLLOW_ONLY"
MODE_PATROL_FOLLOW = "PATROL_FOLLOW"

_LATEST_STATUS = {
    "mode": "INIT",
    "pose": False,
    "state": "startup",
    "hold_timer_s": 0.0,
    "distance_cm": None,
    "cmd": "MS",
    "seek_active": False,
    "tracking_online": False,
}
_LATEST_STATUS_LOCK = Lock()


def update_status(
    *,
    mode: str,
    pose: bool,
    state: str,
    hold_timer_s: float,
    distance_cm: float | None,
    cmd: str,
    seek_active: bool,
    tracking_online: bool,
) -> None:
    with _LATEST_STATUS_LOCK:
        _LATEST_STATUS["mode"] = mode
        _LATEST_STATUS["pose"] = bool(pose)
        _LATEST_STATUS["state"] = state
        _LATEST_STATUS["hold_timer_s"] = round(max(0.0, hold_timer_s), 1)
        _LATEST_STATUS["distance_cm"] = None if distance_cm is None else round(distance_cm, 1)
        _LATEST_STATUS["cmd"] = cmd
        _LATEST_STATUS["seek_active"] = bool(seek_active)
        _LATEST_STATUS["tracking_online"] = bool(tracking_online)


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route != APP_STATUS_PATH:
            self.send_response(404)
            self.end_headers()
            return

        with _LATEST_STATUS_LOCK:
            payload = dict(_LATEST_STATUS)

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_status_server(config: PatrolConfig) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((config.app_status_host, config.app_status_port), StatusHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def make_db_url(path: str) -> str:
    base = FIREBASE_DB_URL.rstrip("/")
    cleaned = path.lstrip("/")
    return f"{base}/{cleaned}.json"


def firebase_put(path: str, value) -> None:
    try:
        requests.put(make_db_url(path), json=value, timeout=0.35)
    except requests.RequestException:
        pass


def firebase_get(path: str):
    try:
        response = requests.get(make_db_url(path), timeout=0.35)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish_display_to_firebase(
    *,
    mode: str,
    pose: bool,
    state: str,
    hold_timer_s: float,
    distance_cm: float | None,
    cmd: str,
    seek_active: bool,
    tracking_online: bool,
) -> None:
    firebase_put(
        FIREBASE_DISPLAY_BASE_PATH,
        {
            "mode": mode,
            "tracking_alarm": bool(pose),
            "tracking_state": state,
            "tracking_online": bool(tracking_online),
            "ultrasonic_cm": None if distance_cm is None else round(float(distance_cm), 1),
            "hold_timer_s": round(max(0.0, hold_timer_s), 1),
            "cmd": cmd,
            "seek_active": bool(seek_active),
            "updated_at": utc_now_iso(),
        },
    )


def normalize_mode_profile(value) -> str:
    if not isinstance(value, str):
        return MODE_PATROL_FOLLOW

    normalized = value.strip().upper()
    if normalized in {MODE_IDLE, MODE_PATROL_ONLY, MODE_FOLLOW_ONLY, MODE_PATROL_FOLLOW}:
        return normalized
    return MODE_PATROL_FOLLOW


class BotController:
    def __init__(self, cmd_url: str, cmd_timeout_s: float, cmd_min_interval_s: float) -> None:
        self.cmd_url = cmd_url
        self.cmd_timeout_s = cmd_timeout_s
        self.cmd_min_interval_s = cmd_min_interval_s
        self.last_cmd = ""
        self.last_sent_at = 0.0

    def send(self, cmd: str, force: bool = False) -> bool:
        now = time.time()
        if not force and cmd == self.last_cmd and (now - self.last_sent_at) < self.cmd_min_interval_s:
            return True

        try:
            response = requests.get(self.cmd_url, params={"p": cmd}, timeout=self.cmd_timeout_s)
            if response.ok:
                self.last_cmd = cmd
                self.last_sent_at = now
                print(f"[patrol-cmd] {cmd}")
                return True
        except requests.RequestException:
            return False

        return False


def read_distance_cm(status_url: str, timeout_s: float) -> float | None:
    try:
        response = requests.get(status_url, timeout=timeout_s)
        response.raise_for_status()
        text = response.text
    except requests.RequestException:
        return None

    match = re.search(r"D:([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def read_tracking_pose(status_url: str, timeout_s: float) -> tuple[bool, bool, str, str | None]:
    try:
        response = requests.get(status_url, timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()

        pose = bool(payload.get("pose", False))
        tracking_state = str(payload.get("state", "-"))
        tracking_cmd_raw = payload.get("cmd")
        tracking_cmd = str(tracking_cmd_raw) if tracking_cmd_raw is not None else None
        return pose, True, tracking_state, tracking_cmd
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
        return False, False, "offline", None


def avoid_obstacle(bot: BotController, config: PatrolConfig, turn_left_next: bool) -> bool:
    turn_cmd = f"ML{config.turn_speed}" if turn_left_next else f"MR{config.turn_speed}"

    bot.send("MS", force=True)
    time.sleep(config.stop_before_turn_s)

    bot.send(f"MB{config.reverse_speed}", force=True)
    time.sleep(config.reverse_time_s)

    bot.send("MS", force=True)
    time.sleep(config.stop_after_reverse_s)

    bot.send(turn_cmd, force=True)
    time.sleep(config.turn_135_time_s)

    bot.send("MS", force=True)
    return not turn_left_next


def get_tracking_script_name(tracking_backend: str) -> str:
    backend = tracking_backend.strip().lower()
    if backend == "yolo":
        return "tracking_yolo.py"
    return "tracking.py"


def start_tracking_process(config: PatrolConfig) -> subprocess.Popen | None:
    if not config.tracking_autostart:
        return None

    script_name = get_tracking_script_name(config.tracking_backend)
    script_path = Path(__file__).resolve().parent / script_name

    if not script_path.exists():
        print(f"[patrol] tracking script not found: {script_path}")
        return None

    cmd = [sys.executable, str(script_path)]
    print(f"[patrol] starting tracking backend '{config.tracking_backend}' via: {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def main() -> None:
    config = PatrolConfig()

    cmd_url = f"http://{config.bot_ip}/cmd"
    bot_status_url = f"http://{config.bot_ip}/status"

    status_server = start_status_server(config)
    tracking_process = start_tracking_process(config)
    bot = BotController(
        cmd_url=cmd_url,
        cmd_timeout_s=config.cmd_timeout_s,
        cmd_min_interval_s=config.cmd_min_interval_s,
    )

    last_pose_seen_at = 0.0
    last_pose_flag = False
    turn_left_next = True
    last_distance = None
    last_firebase_write_at = 0.0
    last_control_read_at = 0.0
    last_tracking_cmd = "MS"
    last_follow_log_state = ""
    last_follow_log_cmd = ""
    mode_profile = normalize_mode_profile(firebase_get(FIREBASE_CONTROL_MODE_PATH))

    print("Patrol Controller started (without camera access)")
    print(f"Tracking backend: {config.tracking_backend}")
    print(f"Tracking autostart: {config.tracking_autostart}")
    print(f"Tracking status source: {config.tracking_status_url}")
    print(f"App status endpoint: http://127.0.0.1:{config.app_status_port}{APP_STATUS_PATH}")
    print("Execution modes: IDLE / PATROL_ONLY / FOLLOW_ONLY / PATROL_FOLLOW")

    try:
        while True:
            now = time.time()

            if (now - last_control_read_at) >= FIREBASE_CONTROL_READ_INTERVAL_S:
                remote_profile = normalize_mode_profile(firebase_get(FIREBASE_CONTROL_MODE_PATH))
                mode_profile = remote_profile
                last_control_read_at = now

            pose_detected, tracking_online, tracking_state, tracking_cmd = read_tracking_pose(
                config.tracking_status_url,
                config.tracking_status_timeout_s,
            )

            if tracking_cmd is not None and tracking_cmd.startswith("M"):
                last_tracking_cmd = tracking_cmd

            if pose_detected and (not last_pose_flag or config.refresh_hold_on_continuous_pose):
                last_pose_seen_at = now

            last_pose_flag = pose_detected

            hold_left = max(0.0, config.pose_hold_seconds - (now - last_pose_seen_at))
            in_pose_hold = hold_left > 0.0
            active_hold_s = 0.0
            seek_active = False

            if mode_profile == MODE_IDLE:
                mode = "IDLE"
                cmd = "MS"
                state = "remote: idle"
                bot.send(cmd)
                last_distance = read_distance_cm(bot_status_url, config.bot_status_timeout_s)
            elif mode_profile == MODE_PATROL_ONLY:
                mode = "PATROL"
                last_distance = read_distance_cm(bot_status_url, config.bot_status_timeout_s)
                if last_distance is not None and last_distance < config.obstacle_threshold_cm:
                    state = f"obstacle {last_distance:.1f}cm -> avoid"
                    turn_left_next = avoid_obstacle(bot, config, turn_left_next)
                    cmd = "MS"
                else:
                    cmd = f"MF{config.forward_speed}"
                    bot.send(cmd)
                    if last_distance is None:
                        state = "forward (distance n/a)"
                    else:
                        state = f"forward ({last_distance:.1f}cm)"
            elif mode_profile == MODE_FOLLOW_ONLY:
                mode = "FOLLOW"
                cmd = last_tracking_cmd
                seek_active = "seek" in tracking_state.lower()
                state = f"tracking:{tracking_state} | seek={seek_active} | cmd={cmd}"
                bot.send(cmd)
                last_distance = None
            else:
                if pose_detected and tracking_online:
                    mode = "FOLLOW"
                    cmd = tracking_cmd if tracking_cmd.startswith("M") else "MS"
                    seek_active = "seek" in tracking_state.lower()
                    state = f"tracking:{tracking_state} | seek={seek_active} | cmd={cmd}"
                    last_distance = None
                    bot.send(cmd)
                elif in_pose_hold:
                    cmd = "MS"
                    state = "pose lost -> hold"
                    mode = f"HOLD FOR {hold_left:.1f}S"
                    bot.send(cmd)
                    active_hold_s = hold_left
                else:
                    mode = "PATROL"
                    last_distance = read_distance_cm(bot_status_url, config.bot_status_timeout_s)

                    if last_distance is not None and last_distance < config.obstacle_threshold_cm:
                        state = f"obstacle {last_distance:.1f}cm -> avoid"
                        turn_left_next = avoid_obstacle(bot, config, turn_left_next)
                        cmd = "MS"
                    else:
                        cmd = f"MF{config.forward_speed}"
                        bot.send(cmd)
                        if last_distance is None:
                            state = "forward (distance n/a)"
                        else:
                            state = f"forward ({last_distance:.1f}cm)"

            status_pose = pose_detected
            status_hold_s = active_hold_s
            status_distance_cm = last_distance
            if mode == "FOLLOW":
                status_pose = False
                status_hold_s = 0.0
                status_distance_cm = None

            update_status(
                mode=mode,
                pose=status_pose,
                state=state,
                hold_timer_s=status_hold_s,
                distance_cm=status_distance_cm,
                cmd=cmd,
                seek_active=seek_active,
                tracking_online=tracking_online,
            )

            if mode == "FOLLOW" and (state != last_follow_log_state or cmd != last_follow_log_cmd):
                print(f"[patrol-follow] {state}")
                last_follow_log_state = state
                last_follow_log_cmd = cmd

            if (now - last_firebase_write_at) >= FIREBASE_WRITE_INTERVAL_S:
                publish_display_to_firebase(
                    mode=mode,
                    pose=status_pose,
                    state=state,
                    hold_timer_s=status_hold_s,
                    distance_cm=status_distance_cm,
                    cmd=cmd,
                    seek_active=seek_active,
                    tracking_online=tracking_online,
                )
                last_firebase_write_at = now

            time.sleep(config.loop_sleep_s)

    except KeyboardInterrupt:
        print("\nPatrol Controller stopped")
    finally:
        bot.send("MS", force=True)
        status_server.shutdown()
        status_server.server_close()
        if tracking_process is not None:
            tracking_process.terminate()
            try:
                tracking_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                tracking_process.kill()


if __name__ == "__main__":
    main()
