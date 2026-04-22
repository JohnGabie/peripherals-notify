"""
Attack Shark X6 Mouse Battery Notifier

Protocol (reverse-engineered via Attack Shark X11 driver):
  VID=0x1D57
  PID=0xFA60  wireless 2.4GHz dongle
  PID=0xFA61  wired USB
  HID usage_page=0x000A, usage=0x0000 (interface 2, Col03)

  Battery packet header: [0x03, 0x10, 0x40, 0x01]
    data[4] = battery level on a 0-10 bar scale (10 = 100%, multiply by 10)

  Note: battery packets are only sent while discharging wirelessly.
  When charging or wired, no battery packets are emitted.
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

# ── Device ───────────────────────────────────────────────────────────────────

VENDOR_ID  = 0x1D57   # PID varies: 0xFA60=wireless, 0xFA61=wired
USAGE_PAGE = 0x000A

BATTERY_HEADER = (0x03, 0x10, 0x40, 0x01)
BATTERY_BYTE_INDEX = 4

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS    = [30, 20, 10]   # alert at these % levels
POLL_INTERVAL_SECONDS = 60


# ── HID ───────────────────────────────────────────────────────────────────────

def _device_paths() -> list[bytes]:
    return [d["path"] for d in hid.enumerate(VENDOR_ID) if d["usage_page"] == USAGE_PAGE]


def _try_read(path: bytes, retries: int = 10) -> Optional[int]:
    try:
        dev = hid.device()
        dev.open_path(path)
        dev.set_nonblocking(1)
        for _ in range(retries):
            data = dev.read(64, timeout_ms=500)
            if not data or len(data) <= BATTERY_BYTE_INDEX:
                continue
            if tuple(data[:4]) == BATTERY_HEADER:
                pct = data[BATTERY_BYTE_INDEX] * 10  # 0-10 bar scale → 0-100%
                if 0 <= pct <= 100:
                    dev.close()
                    return pct
        dev.close()
    except Exception as e:
        log.debug("HID read error: %s", e)
    return None


def read_battery() -> Optional[int]:
    """Return battery percentage (0-100), or None when unavailable.

    Battery packets are only sent while discharging wirelessly.
    Returns None when charging or connected via USB.
    """
    for path in _device_paths():
        pct = _try_read(path)
        if pct is not None:
            return pct
    return None


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify_plyer(title: str, message: str) -> bool:
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Mouse Battery",
            timeout=8,
        )
        return True
    except Exception:
        return False


def _notify_linux(title: str, message: str) -> bool:
    import subprocess
    try:
        subprocess.run(
            ["notify-send", "-u", "critical", "-t", "8000", title, message],
            check=True,
            capture_output=True,
        )
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
        "Attack Shark X6 battery monitor started  "
        "(thresholds=%s  poll=%ds)",
        thresholds, poll,
    )

    while True:
        pct = read_battery()

        if pct is None:
            if state.last_pct is not None:
                log.warning("Mouse not found — is it disconnected?")
                state.last_pct = None
                state.triggered.clear()
        else:
            if pct != state.last_pct:
                log.info("Battery: %d%%", pct)

            # If battery went up (reconnected / charged), reset fired alerts
            if state.last_pct is not None and pct > state.last_pct:
                state.triggered = {t for t in state.triggered if t >= pct}

            state.last_pct = pct

            for threshold in thresholds:
                if pct <= threshold and threshold not in state.triggered:
                    state.triggered.add(threshold)
                    if pct <= 10:
                        title = "Bateria critica do mouse!"
                        msg = f"Attack Shark X6: {pct}% — conecte o cabo agora!"
                    else:
                        title = "Mouse com bateria baixa"
                        msg = f"Attack Shark X6: {pct}% de bateria restante."
                    send_notification(title, msg)

        time.sleep(poll)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Attack Shark X6 battery notifier")
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
        help="Read battery once, print the result and exit",
    )
    args = parser.parse_args()

    if args.once:
        pct = read_battery()
        if pct is None:
            print("Mouse not found or not connected via dongle.")
            sys.exit(1)
        print(f"Battery: {pct}%")
        sys.exit(0)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
