import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import requests


@dataclass
class PatrolConfig:
    # bot_ip: str = "192.168.1.108"
    bot_ip: str = "172.20.10.6"


    obstacle_threshold_cm: float = 20.0
    forward_speed: int = 95
    turn_speed: int = 120
    reverse_speed: int = 85

    reverse_time_s: float = 0.60
    stop_before_turn_s: float = 0.08
    stop_after_reverse_s: float = 0.08
    turn_135_time_s: float = 0.95

    pose_hold_seconds: float = 500.0
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

_LATEST_STATUS = {
    "mode": "INIT",
    "pose": False,
    "state": "startup",
    "hold_timer_s": 0.0,
    "distance_cm": None,
    "cmd": "MS",
    "tracking_online": False,
}
_LATEST_STATUS_LOCK = Lock()


def update_status(*, mode: str, pose: bool, state: str, hold_timer_s: float, distance_cm: float | None, cmd: str, tracking_online: bool) -> None:
    with _LATEST_STATUS_LOCK:
        _LATEST_STATUS["mode"] = mode
        _LATEST_STATUS["pose"] = bool(pose)
        _LATEST_STATUS["state"] = state
        _LATEST_STATUS["hold_timer_s"] = round(max(0.0, hold_timer_s), 1)
        _LATEST_STATUS["distance_cm"] = None if distance_cm is None else round(distance_cm, 1)
        _LATEST_STATUS["cmd"] = cmd
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


def read_tracking_pose(status_url: str, timeout_s: float) -> tuple[bool, bool, str, str]:
    try:
        response = requests.get(status_url, timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()

        pose = bool(payload.get("pose", False))
        tracking_state = str(payload.get("state", "-"))
        tracking_cmd = str(payload.get("cmd", "MS"))
        return pose, True, tracking_state, tracking_cmd
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError):
        return False, False, "offline", "MS"


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
    last_log_at = 0.0

    print("Patrol Controller gestartet (ohne Kamerazugriff)")
    print(f"Tracking backend: {config.tracking_backend}")
    print(f"Tracking autostart: {config.tracking_autostart}")
    print(f"Tracking status source: {config.tracking_status_url}")
    print(f"App status endpoint: http://127.0.0.1:{config.app_status_port}{APP_STATUS_PATH}")
    print("Modi: PATROL / FOLLOW / POSE_HOLD")

    try:
        while True:
            now = time.time()

            pose_detected, tracking_online, tracking_state, tracking_cmd = read_tracking_pose(
                config.tracking_status_url,
                config.tracking_status_timeout_s,
            )

            if pose_detected and (not last_pose_flag or config.refresh_hold_on_continuous_pose):
                last_pose_seen_at = now

            last_pose_flag = pose_detected

            hold_left = max(0.0, config.pose_hold_seconds - (now - last_pose_seen_at))
            in_pose_hold = hold_left > 0.0

            if pose_detected and tracking_online:
                mode = "FOLLOW"
                cmd = tracking_cmd if tracking_cmd.startswith("M") else "MS"
                state = f"tracking:{tracking_state}"
                bot.send(cmd)
            elif in_pose_hold:
                cmd = "MS"
                state = "pose verloren -> hold"
                mode = "POSE_HOLD"
                bot.send(cmd)
            else:
                mode = "PATROL"
                last_distance = read_distance_cm(bot_status_url, config.bot_status_timeout_s)

                if last_distance is not None and last_distance < config.obstacle_threshold_cm:
                    state = f"hindernis {last_distance:.1f}cm -> avoid"
                    turn_left_next = avoid_obstacle(bot, config, turn_left_next)
                    cmd = "MS"
                else:
                    cmd = f"MF{config.forward_speed}"
                    bot.send(cmd)
                    if last_distance is None:
                        state = "vorwaerts (distanz n/a)"
                    else:
                        state = f"vorwaerts ({last_distance:.1f}cm)"

            update_status(
                mode=mode,
                pose=pose_detected,
                state=state,
                hold_timer_s=hold_left if (in_pose_hold and not pose_detected) else 0.0,
                distance_cm=last_distance,
                cmd=cmd,
                tracking_online=tracking_online,
            )

            if (now - last_log_at) >= 1.0:
                print(
                    f"[patrol] mode={mode} pose={pose_detected} hold={hold_left:.1f}s "
                    f"dist={('-' if last_distance is None else f'{last_distance:.1f}cm')}"
                )
                last_log_at = now

            time.sleep(config.loop_sleep_s)

    except KeyboardInterrupt:
        print("\nPatrol Controller beendet")
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
