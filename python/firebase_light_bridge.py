import time
from datetime import datetime, timezone

import requests

# --- CONFIG ---
BOT_IP = "192.168.1.108"
FIREBASE_DB_URL = "https://iot-alarm-app-b4b9c-default-rtdb.europe-west1.firebasedatabase.app"

# Preferred path first, legacy fallback second.
FIREBASE_LIGHT_PATHS = [
    "bots/alphabot/light_on",
    "bots/alphabot/camera/light_on",
]

# Optional status paths for debugging in Firebase.
FIREBASE_BRIDGE_STATUS_PATH = "bots/alphabot/light_bridge/status"
FIREBASE_BRIDGE_LAST_APPLIED_PATH = "bots/alphabot/light_bridge/last_applied"

POLL_INTERVAL_S = 0.35
HTTP_TIMEOUT_S = 0.5

ESP_CMD_URL = f"http://{BOT_IP}/cmd"


def make_db_url(path: str) -> str:
    base = FIREBASE_DB_URL.rstrip("/")
    cleaned = path.lstrip("/")
    return f"{base}/{cleaned}.json"


def firebase_get(path: str):
    try:
        response = requests.get(make_db_url(path), timeout=HTTP_TIMEOUT_S)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def firebase_put(path: str, value) -> None:
    try:
        requests.put(make_db_url(path), json=value, timeout=HTTP_TIMEOUT_S)
    except requests.RequestException:
        pass


def read_light_state() -> tuple[bool | None, str | None]:
    for path in FIREBASE_LIGHT_PATHS:
        value = firebase_get(path)
        if isinstance(value, bool):
            return value, path
    return None, None


def send_light_to_esp(light_on: bool) -> bool:
    command = "L1" if light_on else "L0"
    try:
        response = requests.get(ESP_CMD_URL, params={"p": command}, timeout=HTTP_TIMEOUT_S)
        return response.ok
    except requests.RequestException:
        return False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    print("Firebase Light Bridge gestartet")
    print(f"Firebase: {FIREBASE_DB_URL}")
    print(f"ESP: http://{BOT_IP}")
    print(f"Watch paths: {FIREBASE_LIGHT_PATHS}")

    last_seen_state = None

    firebase_put(FIREBASE_BRIDGE_STATUS_PATH, {"online": True, "updated_at": utc_now_iso()})

    try:
        while True:
            desired_state, source_path = read_light_state()

            if desired_state is None:
                firebase_put(FIREBASE_BRIDGE_STATUS_PATH, {
                    "online": True,
                    "updated_at": utc_now_iso(),
                    "error": "no_boolean_light_value_found",
                })
                time.sleep(POLL_INTERVAL_S)
                continue

            if desired_state != last_seen_state:
                ok = send_light_to_esp(desired_state)

                firebase_put(FIREBASE_BRIDGE_LAST_APPLIED_PATH, {
                    "value": desired_state,
                    "source_path": source_path,
                    "applied_ok": ok,
                    "updated_at": utc_now_iso(),
                })

                if ok:
                    print(f"Applied {'ON' if desired_state else 'OFF'} from {source_path}")
                    last_seen_state = desired_state
                else:
                    print("ESP command failed, will retry on next poll")

            firebase_put(FIREBASE_BRIDGE_STATUS_PATH, {
                "online": True,
                "updated_at": utc_now_iso(),
                "watching": source_path,
            })
            time.sleep(POLL_INTERVAL_S)

    except KeyboardInterrupt:
        print("Bridge gestoppt")
    finally:
        firebase_put(FIREBASE_BRIDGE_STATUS_PATH, {"online": False, "updated_at": utc_now_iso()})


if __name__ == "__main__":
    main()
