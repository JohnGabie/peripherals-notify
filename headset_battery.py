"""
Logitech G PRO X 2 LIGHTSPEED Headset Battery Notifier

Protocol (reverse-engineered, no G HUB required):
  VID=0x046D, PID=0x0AF7
  Interface 3, usage_page=0xFFA0 (Centurion vendor transport)
  Report ID 0x51, 64-byte frames.

  Request:  [0x51, 0x08, 0x00, 0x03, 0x1a, 0x00, 0x03, 0x00, 0x04, 0x0a, 0x00*54]
  Response: two packets —
    ACK:     0x51 0x03 ...  (discard)
    BATTERY: 0x51 0x0b ...  byte[10]=pct(0-100)  byte[12]=charging(0x02=yes)
"""

import sys
import time
import platform
import logging
from dataclasses import dataclass, field
from typing import Optional

import hid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Device ────────────────────────────────────────────────────────────────────

VENDOR_ID  = 0x046D
PRODUCT_ID = 0x0AF7
USAGE_PAGE = 0xFFA0
FRAME_SIZE = 64

BATTERY_REQUEST = bytes([
    0x51, 0x08, 0x00,
    0x03,        # headset subdevice index
    0x1a,        # battery feature index
    0x00,
    0x03, 0x00,
    0x04, 0x0a,
]) + b"\x00" * (FRAME_SIZE - 10)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS    = [30, 20, 10]
POLL_INTERVAL_SECONDS = 60


# ── HID ───────────────────────────────────────────────────────────────────────

def find_device_path() -> Optional[bytes]:
    for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        if d["usage_page"] == USAGE_PAGE:
            return d["path"]
    return None


def read_battery() -> Optional[int]:
    """Return headset battery percentage (0-100), or None when unavailable."""
    path = find_device_path()
    if path is None:
        return None
    try:
        dev = hid.device()
        dev.open_path(path)
        try:
            if dev.write(BATTERY_REQUEST) < 0:
                return None
            # Read up to 5 frames; skip ACK (0x51 0x03), take battery (0x51 0x0b)
            for _ in range(5):
                data = dev.read(FRAME_SIZE, timeout_ms=1500)
                if not data:
                    break
                if data[0] == 0x51 and data[1] == 0x0b and len(data) > 10:
                    return data[10]
        finally:
            dev.close()
    except Exception as e:
        log.debug("HID read error: %s", e)
    return None


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify_plyer(title: str, message: str) -> bool:
    try:
        from plyer import notification
        notification.notify(title=title, message=message,
                            app_name="Headset Battery", timeout=8)
        return True
    except Exception:
        return False


def _notify_linux(title: str, message: str) -> bool:
    import subprocess
    try:
        subprocess.run(["notify-send", "-u", "critical", "-t", "8000", title, message],
                       check=True, capture_output=True)
        return True
    except Exception:
        return False


def send_notification(title: str, message: str) -> None:
    log.info("NOTIFY  %s — %s", title, message)
    if _notify_plyer(title, message):
        return
    if platform.system() == "Linux":
        _notify_linux(title, message)


# ── Main loop ─────────────────────────────────────────────────────────────────

@dataclass
class _State:
    last_pct: Optional[int] = None
    triggered: set = field(default_factory=set)


def run(thresholds: list[int] = DEFAULT_THRESHOLDS,
        poll: int = POLL_INTERVAL_SECONDS) -> None:

    state = _State()
    thresholds = sorted(thresholds, reverse=True)

    log.info(
        "G PRO X 2 LIGHTSPEED battery monitor started  "
        "(thresholds=%s  poll=%ds)",
        thresholds, poll,
    )

    while True:
        pct = read_battery()

        if pct is None:
            if state.last_pct is not None:
                log.warning("Headset not found — is it connected?")
                state.last_pct = None
                state.triggered.clear()
        else:
            if pct != state.last_pct:
                log.info("Battery: %d%%", pct)

            if state.last_pct is not None and pct > state.last_pct:
                state.triggered = {t for t in state.triggered if t >= pct}

            state.last_pct = pct

            for threshold in thresholds:
                if pct <= threshold and threshold not in state.triggered:
                    state.triggered.add(threshold)
                    if pct <= 10:
                        title = "Bateria critica do fone!"
                        msg = f"G PRO X 2 LIGHTSPEED: {pct}% — carregue agora!"
                    else:
                        title = "Fone com bateria baixa"
                        msg = f"G PRO X 2 LIGHTSPEED: {pct}% de bateria restante."
                    send_notification(title, msg)

        time.sleep(poll)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Logitech G PRO X 2 LIGHTSPEED battery notifier"
    )
    parser.add_argument(
        "--thresholds", nargs="+", type=int, default=DEFAULT_THRESHOLDS,
        metavar="PCT",
        help="Battery %% levels that trigger alerts (default: 30 20 10)",
    )
    parser.add_argument(
        "--poll", type=int, default=POLL_INTERVAL_SECONDS,
        metavar="SECONDS",
        help="Polling interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Read battery once, print result and exit",
    )
    args = parser.parse_args()

    if args.once:
        pct = read_battery()
        if pct is None:
            print("Headset not found or not responding.")
            sys.exit(1)
        print(f"Battery: {pct}%")
        sys.exit(0)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
