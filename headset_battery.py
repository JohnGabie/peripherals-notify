"""
Logitech G PRO X 2 LIGHTSPEED Headset Battery Notifier

Protocol (reverse-engineered, no G HUB required; fields checked against
G HUB's own battery state from its local agent API):
  VID=0x046D, PID=0x0AF7
  Interface 3, usage_page=0xFFA0 (Centurion vendor transport)
  Report ID 0x51, 64-byte frames.

  Request:  [0x51, 0x08, 0x00, 0x03, 0x1a, 0x00, 0x03, 0x00, 0x04, 0x0a, 0x00*54]
  Replies:
    ACK:     51 03 ...                        (discard)
    BATTERY: 51 0b 00 03 10 00 06 00 04 0a P P S
             byte[10] = battery % (the number G HUB shows; byte[11] repeats it)
             byte[12] = status: 0x00 discharging, 0x02 charging
    ERROR:   51 05 00 ff 03 1a 0b ...         headset off / out of range

  While charging the % reads high, so G HUB keeps showing the last value and
  only "charging"; this module does the same. Right after a charge the % can
  stay high until the headset restarts and re-estimates it.
"""

import sys
import time
import platform
import logging
from dataclasses import dataclass, field
from enum import Enum
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
REPORT_ID  = 0x51

BATTERY_REQUEST = bytes([
    0x51, 0x08, 0x00,
    0x03,        # headset subdevice index
    0x1a,        # battery feature index
    0x00,
    0x03, 0x00,
    0x04, 0x0a,
]) + b"\x00" * (FRAME_SIZE - 10)

KIND_ACK     = 0x03
KIND_BATTERY = 0x0b
ERROR_MARK   = 0xff          # byte[3] of an error reply

PCT_INDEX    = 10
STATUS_INDEX = 12
STATUS_DISCHARGING = 0x00
STATUS_CHARGING    = 0x02

MAX_LIFE_HOURS = 50          # G HUB's maxLifeSpan for this headset

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS    = [30, 20, 10]
POLL_INTERVAL_SECONDS = 60


# ── Status ────────────────────────────────────────────────────────────────────

class HeadsetState(Enum):
    NOT_FOUND   = "not_found"     # receiver not plugged in
    OFF         = "off"           # receiver present, headset off or out of range
    DISCHARGING = "discharging"
    CHARGING    = "charging"


@dataclass(frozen=True)
class HeadsetStatus:
    state: HeadsetState
    pct: Optional[int] = None     # None when unknown or unreliable (charging)

    @property
    def hours_left(self) -> Optional[float]:
        if self.state != HeadsetState.DISCHARGING or self.pct is None:
            return None
        return self.pct * MAX_LIFE_HOURS / 100


def parse_reply(data: list[int]) -> Optional[HeadsetStatus]:
    """Return the status carried by one reply frame, or None for ACKs and other frames."""
    if len(data) < 4 or data[0] != REPORT_ID:
        return None
    if data[3] == ERROR_MARK:
        return HeadsetStatus(HeadsetState.OFF)
    if data[1] != KIND_BATTERY or len(data) <= STATUS_INDEX:
        return None
    pct, status = data[PCT_INDEX], data[STATUS_INDEX]
    if not 0 <= pct <= 100:
        return None
    if status == STATUS_DISCHARGING:
        return HeadsetStatus(HeadsetState.DISCHARGING, pct)
    if status != STATUS_CHARGING:
        log.debug("Unknown headset battery status %#04x (pct=%d)", status, pct)
    return HeadsetStatus(HeadsetState.CHARGING)


# ── HID ───────────────────────────────────────────────────────────────────────

def find_device_path() -> Optional[bytes]:
    for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        if d["usage_page"] == USAGE_PAGE:
            return d["path"]
    return None


def read_status() -> HeadsetStatus:
    """Ask the headset for its battery and return the decoded state."""
    path = find_device_path()
    if path is None:
        return HeadsetStatus(HeadsetState.NOT_FOUND)
    try:
        dev = hid.device()
        dev.open_path(path)
        try:
            if dev.write(BATTERY_REQUEST) < 0:
                return HeadsetStatus(HeadsetState.OFF)
            # Skip the ACK; take the battery or error reply.
            for _ in range(5):
                data = dev.read(FRAME_SIZE, timeout_ms=1500)
                if not data:
                    break
                status = parse_reply(data)
                if status is not None:
                    return status
        finally:
            dev.close()
    except Exception as e:
        log.debug("HID read error: %s", e)
    return HeadsetStatus(HeadsetState.OFF)


def read_battery() -> Optional[int]:
    """Return headset battery percentage (0-100) while discharging, else None.

    Kept for callers that only alert on low battery: charging and off
    states return None so no low-battery alert fires while charging.
    """
    status = read_status()
    if status.state == HeadsetState.DISCHARGING:
        return status.pct
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

_STATE_TEXT = {
    HeadsetState.NOT_FOUND:   "receptor não encontrado",
    HeadsetState.OFF:         "desligado ou fora de alcance",
    HeadsetState.DISCHARGING: "descarregando",
    HeadsetState.CHARGING:    "carregando",
}


def describe(status: HeadsetStatus) -> str:
    text = _STATE_TEXT[status.state]
    if status.state == HeadsetState.DISCHARGING and status.pct is not None:
        return f"{text}, {status.pct}% (~{status.hours_left:.0f} h)"
    return text


@dataclass
class _State:
    last: Optional[HeadsetStatus] = None
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
        status = read_status()

        if status != state.last:
            log.info("Headset: %s", describe(status))

        # Charging resets fired alerts so they fire again on the next discharge.
        if status.state == HeadsetState.CHARGING:
            state.triggered.clear()

        if status.state == HeadsetState.DISCHARGING and status.pct is not None:
            pct = status.pct
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

        state.last = status
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
        help="Read the headset state once, print it and exit",
    )
    args = parser.parse_args()

    if args.once:
        status = read_status()
        print(f"Headset: {describe(status)}")
        sys.exit(0 if status.state != HeadsetState.NOT_FOUND else 1)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
