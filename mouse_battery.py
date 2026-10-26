"""
Attack Shark X6 Mouse Battery Notifier

Protocol (reverse-engineered from the vendor app X6.exe + hiddriver_1.dll):
  VID=0x1D57
  PID=0xFA60  2.4GHz dongle
  PID=0xFA61  USB cable (only enumerated while the cable is plugged in)
  HID usage_page=0x000A, usage=0x0000 (interface 2) — input reports

  Every input report with ID 0x03 carries two little-endian u16 values:
    code  = data[1] | data[2] << 8
    value = data[3] | data[4] << 8

  code 0x4010 = battery status, sent every ~2 s while the mouse is awake:
    data[3] = status  (1 = discharging, 2 = full, 3 = charging)
    data[4] = level   (1-10 bars, x10 = %)

  States, as the vendor app derives them:
    - no 0x4010 for 6 s on the dongle  -> mouse off or asleep
    - cable interface (0xFA61) present -> charging
    - status 2                         -> full
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

# ── Device ───────────────────────────────────────────────────────────────────

VENDOR_ID  = 0x1D57
PID_DONGLE = 0xFA60
PID_CABLE  = 0xFA61
USAGE_PAGE = 0x000A

REPORT_ID      = 0x03
CODE_BATTERY   = 0x4010
STATUS_DISCHARGING = 1
STATUS_FULL        = 2
STATUS_CHARGING    = 3

# Battery reports arrive every ~2 s; the vendor app gives up after 6 s.
READ_WINDOW_SECONDS = 4.5

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS    = [30, 20, 10]   # alert at these % levels
POLL_INTERVAL_SECONDS = 60


# ── Status ────────────────────────────────────────────────────────────────────

class MouseState(Enum):
    NOT_FOUND   = "not_found"     # no dongle and no cable
    OFF         = "off"           # dongle present, mouse silent (off or asleep)
    DISCHARGING = "discharging"
    CHARGING    = "charging"
    FULL        = "full"


@dataclass(frozen=True)
class MouseStatus:
    state: MouseState
    pct: Optional[int] = None     # None when unknown


def parse_report(data: list[int]) -> Optional[tuple[int, int]]:
    """Return (status, pct) from a battery input report, or None for any other report."""
    if len(data) < 5 or data[0] != REPORT_ID:
        return None
    if data[1] | data[2] << 8 != CODE_BATTERY:
        return None
    status, level = data[3], data[4]
    if status not in (STATUS_DISCHARGING, STATUS_FULL, STATUS_CHARGING):
        return None
    if not 0 <= level <= 10:
        return None
    return status, level * 10


def _status_from_report(status: int, pct: int, cable: bool) -> MouseStatus:
    if status == STATUS_FULL:
        return MouseStatus(MouseState.FULL, 100)
    if status == STATUS_CHARGING or cable:
        return MouseStatus(MouseState.CHARGING, pct)
    return MouseStatus(MouseState.DISCHARGING, pct)


# ── HID ───────────────────────────────────────────────────────────────────────

def _open_interfaces() -> list[tuple[int, "hid.device"]]:
    handles = []
    for d in hid.enumerate(VENDOR_ID):
        if d["usage_page"] != USAGE_PAGE:
            continue
        if d["product_id"] not in (PID_DONGLE, PID_CABLE):
            continue
        try:
            dev = hid.device()
            dev.open_path(d["path"])
            dev.set_nonblocking(1)
            handles.append((d["product_id"], dev))
        except Exception as e:
            log.debug("Cannot open %#06x: %s", d["product_id"], e)
    return handles


def read_status(window: float = READ_WINDOW_SECONDS) -> MouseStatus:
    """Listen to the dongle and cable interfaces and return the mouse state."""
    handles = _open_interfaces()
    if not handles:
        return MouseStatus(MouseState.NOT_FOUND)

    cable = any(pid == PID_CABLE for pid, _ in handles)
    try:
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            for pid, dev in handles:
                try:
                    data = dev.read(64)
                except Exception as e:
                    log.debug("HID read error on %#06x: %s", pid, e)
                    continue
                parsed = parse_report(data) if data else None
                if parsed:
                    return _status_from_report(*parsed, cable=cable)
            time.sleep(0.02)
    finally:
        for _, dev in handles:
            dev.close()

    # No battery report in the window.
    if cable:
        return MouseStatus(MouseState.CHARGING)
    return MouseStatus(MouseState.OFF)


def read_battery() -> Optional[int]:
    """Return battery percentage (0-100) while discharging, else None.

    Kept for callers that only alert on low battery: charging, full and
    off states return None so no low-battery alert fires while charging.
    """
    status = read_status()
    if status.state == MouseState.DISCHARGING:
        return status.pct
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

_STATE_TEXT = {
    MouseState.NOT_FOUND:   "dongle e cabo não encontrados",
    MouseState.OFF:         "desligado ou dormindo",
    MouseState.DISCHARGING: "descarregando",
    MouseState.CHARGING:    "carregando",
    MouseState.FULL:        "carregado (100%)",
}


def describe(status: MouseStatus) -> str:
    text = _STATE_TEXT[status.state]
    if status.pct is not None and status.state in (MouseState.DISCHARGING, MouseState.CHARGING):
        return f"{text}, {status.pct}%"
    return text


@dataclass
class _State:
    last: Optional[MouseStatus] = None
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
        status = read_status()

        if status != state.last:
            log.info("Mouse: %s", describe(status))

        # Charging resets fired alerts so they fire again on the next discharge.
        if status.state in (MouseState.CHARGING, MouseState.FULL):
            state.triggered.clear()

        if state.last and state.last.state == MouseState.CHARGING \
                and status.state == MouseState.FULL:
            send_notification("Mouse carregado", "Attack Shark X6: 100% — pode tirar o cabo.")

        if status.state == MouseState.DISCHARGING and status.pct is not None:
            pct = status.pct
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

        state.last = status
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
        help="Read the mouse state once, print it and exit",
    )
    args = parser.parse_args()

    if args.once:
        status = read_status()
        print(f"Mouse: {describe(status)}")
        sys.exit(0 if status.state != MouseState.NOT_FOUND else 1)

    try:
        run(thresholds=args.thresholds, poll=args.poll)
    except KeyboardInterrupt:
        log.info("Stopped.")
