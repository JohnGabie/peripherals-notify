"""
Attack Shark K86 Keyboard Battery Notifier (ROYUAN 2.4G Wireless Keyboard)

Protocol (reverse-engineered, no Attack Shark app required):
  VID=0x3151, PID=0x4011
  Interface 2, usage_page=0xFFFF, usage=0x0002 (vendor config)

  No request needed — the dongle maintains a status register that is
  always readable:
    get_feature_report(0x00, 128)
    data[2] = battery % encoded as BCD  (e.g. 0x58 → 58%)
    data[5..7] = [0x01, 0x01, 0x01] when wireless keyboard is connected
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

VENDOR_ID  = 0x3151
PRODUCT_ID = 0x4011
USAGE_PAGE = 0xFFFF
USAGE      = 0x0002
FRAME_SIZE = 128

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS    = [30, 20, 10]
POLL_INTERVAL_SECONDS = 60


# ── HID ───────────────────────────────────────────────────────────────────────

def find_device_path() -> Optional[bytes]:
    for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        if d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE:
            return d["path"]
    return None


def _bcd_to_int(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def read_battery() -> Optional[int]:
    """Return keyboard battery percentage (0-100), or None when unavailable.

    Reads the dongle's status register via get_feature_report(0x00, 128).
    data[2] is BCD-encoded battery % (e.g. 0x58 → 58%).
    data[5..7] == [1, 1, 1] confirms the keyboard is wirelessly connected.
    """
    path = find_device_path()
    if path is None:
        return None
    try:
        dev = hid.device()
        dev.open_path(path)
        try:
            data = dev.get_feature_report(0x00, FRAME_SIZE)
            if not data or len(data) < 8:
                return None
            if data[5] != 0x01 or data[6] != 0x01 or data[7] != 0x01:
                return None  # keyboard not connected to dongle
            pct = _bcd_to_int(data[2])
            if not (0 <= pct <= 100):
                return None
            return pct
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
                            app_name="Keyboard Battery", timeout=8)
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
        "Attack Shark keyboard battery monitor started  "
        "(thresholds=%s  poll=%ds)",
        thresholds, poll,
    )

    while True:
        pct = read_battery()

        if pct is None:
            if state.last_pct is not None:
                log.warning("Keyboard not found.")
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
                        title = "Bateria critica do teclado!"
                        msg = f"Attack Shark Keyboard: {pct}% — carregue agora!"
                    else:
                        title = "Teclado com bateria baixa"
                        msg = f"Attack Shark Keyboard: {pct}% de bateria restante."
                    send_notification(title, msg)

        time.sleep(poll)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Attack Shark keyboard battery notifier")
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
            print("Keyboard not found or not connected to dongle.")
            sys.exit(1)
        print(f"Battery: {pct}%")
        sys.exit(0)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
