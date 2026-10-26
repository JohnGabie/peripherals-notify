"""
Attack Shark K86 Keyboard Battery Notifier (ROYUAN 2.4G Wireless Keyboard)

Protocol (reverse-engineered from the vendor app "Attack Shark Driver v4"
and its iot_driver, no vendor app required):
  VID=0x3151
  PID=0x4011  2.4GHz dongle
  PID=0x4015  USB cable ("Gaming Keyboard", only enumerated while plugged in)
  Dongle interface 2, usage_page=0xFFFF, usage=0x0002 (vendor config)

  No request needed — the dongle keeps a status register that is always
  readable:
    get_feature_report(0x00, 128)
    data[2]    = battery % as a plain byte (e.g. 0x19 → 25%); the vendor
                 driver and UI use it as is, without BCD conversion
    data[4]    = 0x00 while the keyboard is active on the 2.4G link,
                 0x01 when it is not (Bluetooth or cable mode, off, asleep);
                 the battery byte then keeps its last value and is stale
    data[5..7] = [0x01, 0x01, 0x01] while the keyboard is paired to the dongle

  The same register also returns replies to vendor-app commands
  (data[1] != 0x00, e.g. "00 85 00 ..."); those are not status and are retried.

  After ~3-5 min idle the keyboard drops off the 2.4G link (data[4] -> 0x01)
  and a key press wakes it within ~2 s. Turning it off with the switch looks
  the same. Right after power-on the battery byte reads 0 for ~2 s.

  The 2.4G status carries no charging flag; the vendor app cannot show
  charging either. Charging is inferred from the cable interface (0x4015),
  which only enumerates while the keyboard is in cable mode. Charging in
  2.4G mode is not detectable: the battery byte freezes until unplugged.
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

VENDOR_ID  = 0x3151
PID_DONGLE = 0x4011
PID_CABLE  = 0x4015
USAGE_PAGE = 0xFFFF
USAGE      = 0x0002
FRAME_SIZE = 128

FRAME_INDEX    = 1       # 0x00 on status frames, a command code on replies
BATTERY_INDEX  = 2
INACTIVE_INDEX = 4
LINK_SLICE     = slice(5, 8)

# ── Defaults ──────────────────────────────────────────────────────────────────

STATUS_READ_ATTEMPTS = 5
STATUS_RETRY_SECONDS = 0.2

DEFAULT_THRESHOLDS    = [30, 20, 10]
POLL_INTERVAL_SECONDS = 60


# ── Status ────────────────────────────────────────────────────────────────────

class KeyboardState(Enum):
    NOT_FOUND   = "not_found"     # no dongle and no cable
    OFF         = "off"           # dongle present, keyboard not active on 2.4G (off, asleep, Bluetooth)
    DISCHARGING = "discharging"
    CHARGING    = "charging"
    FULL        = "full"


@dataclass(frozen=True)
class KeyboardStatus:
    state: KeyboardState
    pct: Optional[int] = None     # None when unknown


def is_status_frame(data: list[int]) -> bool:
    return len(data) >= 8 and data[FRAME_INDEX] == 0x00


def parse_register(data: list[int]) -> Optional[int]:
    """Return battery % from the dongle status register, or None when not active on 2.4G."""
    if not is_status_frame(data):
        return None
    if data[INACTIVE_INDEX] != 0x00:
        return None   # battery byte is stale
    if list(data[LINK_SLICE]) != [0x01, 0x01, 0x01]:
        return None
    pct = data[BATTERY_INDEX]
    # 0 shows up for ~2 s right after power-on; a keyboard at 0% could not link.
    if not 1 <= pct <= 100:
        return None
    return pct


def _status(pct: Optional[int], dongle: bool, cable: bool) -> KeyboardStatus:
    if cable:
        if pct is not None and pct >= 100:
            return KeyboardStatus(KeyboardState.FULL, 100)
        return KeyboardStatus(KeyboardState.CHARGING, pct)
    if not dongle:
        return KeyboardStatus(KeyboardState.NOT_FOUND)
    if pct is None:
        return KeyboardStatus(KeyboardState.OFF)
    return KeyboardStatus(KeyboardState.DISCHARGING, pct)


# ── HID ───────────────────────────────────────────────────────────────────────

def _read_register(path: bytes) -> Optional[list[int]]:
    """Return the first status frame, skipping replies to vendor-app commands."""
    try:
        dev = hid.device()
        dev.open_path(path)
        try:
            for attempt in range(STATUS_READ_ATTEMPTS):
                data = dev.get_feature_report(0x00, FRAME_SIZE)
                if data and is_status_frame(data):
                    return data
                if attempt + 1 < STATUS_READ_ATTEMPTS:
                    time.sleep(STATUS_RETRY_SECONDS)
        finally:
            dev.close()
    except Exception as e:
        log.debug("HID read error: %s", e)
    return None


def read_status() -> KeyboardStatus:
    """Read the dongle status register and check for the cable interface."""
    dongle_path = None
    cable = False
    for d in hid.enumerate(VENDOR_ID):
        if d["product_id"] == PID_CABLE:
            cable = True
        elif (d["product_id"] == PID_DONGLE
              and d["usage_page"] == USAGE_PAGE and d["usage"] == USAGE):
            dongle_path = d["path"]

    pct = None
    if dongle_path is not None:
        data = _read_register(dongle_path)
        if data:
            pct = parse_register(data)
    return _status(pct, dongle=dongle_path is not None, cable=cable)


def read_battery() -> Optional[int]:
    """Return keyboard battery percentage (0-100) while discharging, else None.

    Kept for callers that only alert on low battery: charging, full and
    off states return None so no low-battery alert fires while charging.
    """
    status = read_status()
    if status.state == KeyboardState.DISCHARGING:
        return status.pct
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

_STATE_TEXT = {
    KeyboardState.NOT_FOUND:   "dongle e cabo não encontrados",
    KeyboardState.OFF:         "desligado, dormindo ou em Bluetooth",
    KeyboardState.DISCHARGING: "descarregando",
    KeyboardState.CHARGING:    "carregando",
    KeyboardState.FULL:        "carregado (100%)",
}


def describe(status: KeyboardStatus) -> str:
    text = _STATE_TEXT[status.state]
    if status.pct is not None and status.state == KeyboardState.DISCHARGING:
        return f"{text}, {status.pct}%"
    return text


@dataclass
class _State:
    last: Optional[KeyboardStatus] = None
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
        status = read_status()

        if status != state.last:
            log.info("Keyboard: %s", describe(status))

        # Charging resets fired alerts so they fire again on the next discharge.
        if status.state in (KeyboardState.CHARGING, KeyboardState.FULL):
            state.triggered.clear()

        if state.last and state.last.state == KeyboardState.CHARGING \
                and status.state == KeyboardState.FULL:
            send_notification("Teclado carregado", "Attack Shark K86: 100% — pode tirar o cabo.")

        if status.state == KeyboardState.DISCHARGING and status.pct is not None:
            pct = status.pct
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

        state.last = status
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
        help="Read the keyboard state once, print it and exit",
    )
    args = parser.parse_args()

    if args.once:
        status = read_status()
        print(f"Keyboard: {describe(status)}")
        sys.exit(0 if status.state != KeyboardState.NOT_FOUND else 1)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
