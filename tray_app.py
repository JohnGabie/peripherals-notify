"""
Battery Monitor — System Tray App

Monitors Attack Shark X6 mouse, K86 keyboard, and Logitech G PRO X 2 headset.
Notifies at 25%, 10%, 5%, 1% per device via native Windows toast notifications.

Tray icon color:
  green  > 25%
  orange 10–25%
  red    ≤ 10%
  grey   all devices disconnected
"""

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import pystray
from PIL import Image, ImageDraw

import mouse_battery
import keyboard_battery
import headset_battery

log = logging.getLogger("tray")

THRESHOLDS   = [25, 10, 5, 1]   # alert at these % levels (per device)
POLL_SECONDS = 60


# ── Notification ──────────────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    log.info("NOTIFY  %s — %s", title, message)
    try:
        from winotify import Notification
        Notification(
            app_id="Battery Monitor",
            title=title,
            msg=message,
            duration="short",
        ).show()
        return
    except Exception:
        pass
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=8)
    except Exception:
        pass


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _battery_color(pct: Optional[int]) -> tuple:
    if pct is None:  return (100, 100, 100)
    if pct > 25:     return (60, 210, 60)
    if pct > 10:     return (255, 165, 0)
    return                  (220, 50, 50)


def _make_icon(pct: Optional[int]) -> Image.Image:
    """Draw a 64×64 RGBA battery icon filled to `pct`%."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    c   = _battery_color(pct)

    d.rectangle([4, 16, 54, 52], outline=c, width=3)   # body outline
    d.rectangle([54, 28, 60, 40], fill=c)               # positive nub

    if pct is not None and pct > 0:
        fill_w = max(1, int(46 * pct / 100))
        d.rectangle([7, 19, 7 + fill_w, 49], fill=c)   # fill bar

    return img


# ── Per-device state ──────────────────────────────────────────────────────────

@dataclass
class _DevState:
    label:     str
    last_pct:  Optional[int] = None
    triggered: set           = field(default_factory=set)


DEVICES: list[_DevState] = [
    _DevState("Mouse X6"),
    _DevState("Teclado K86"),
    _DevState("Fone G PRO X2"),
]

READERS = [
    mouse_battery.read_battery,
    keyboard_battery.read_battery,
    headset_battery.read_battery,
]

_tray_icon: Optional[pystray.Icon] = None


# ── Tray update ───────────────────────────────────────────────────────────────

def _refresh_tray() -> None:
    icon = _tray_icon
    if icon is None:
        return

    levels = [d.last_pct for d in DEVICES if d.last_pct is not None]
    lowest = min(levels) if levels else None

    icon.icon  = _make_icon(lowest)
    icon.title = _tooltip()
    icon.menu  = _build_menu()
    try:
        icon.update_menu()
    except Exception:
        pass


def _tooltip() -> str:
    lines = ["Battery Monitor"]
    for d in DEVICES:
        pct_str = f"{d.last_pct}%" if d.last_pct is not None else "--"
        lines.append(f"  {d.label}: {pct_str}")
    return "\n".join(lines)


def _build_menu() -> pystray.Menu:
    items = []
    for d in DEVICES:
        pct_str = f"{d.last_pct}%" if d.last_pct is not None else "--"
        items.append(pystray.MenuItem(f"{d.label}: {pct_str}", None, enabled=False))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Sair", _quit))
    return pystray.Menu(*items)


def _quit(icon: pystray.Icon, _item) -> None:
    icon.stop()


# ── Monitor thread ────────────────────────────────────────────────────────────

def _run_device(dev: _DevState, read_fn) -> None:
    thresholds = sorted(THRESHOLDS, reverse=True)

    while True:
        try:
            pct = read_fn()
        except Exception as e:
            log.debug("Read error for %s: %s", dev.label, e)
            pct = None

        if pct is None:
            if dev.last_pct is not None:
                log.warning("%s: desconectado", dev.label)
                dev.last_pct  = None
                dev.triggered = set()
                _refresh_tray()
        else:
            if pct != dev.last_pct:
                log.info("%s: %d%%", dev.label, pct)

            # Battery recovered — reset alerts that are now above current level
            if dev.last_pct is not None and pct > dev.last_pct:
                dev.triggered = {t for t in dev.triggered if t >= pct}

            dev.last_pct = pct
            _refresh_tray()

            for t in thresholds:
                if pct <= t and t not in dev.triggered:
                    dev.triggered.add(t)
                    if pct <= 5:
                        title = f"Bateria critica — {dev.label}!"
                        msg   = f"{pct}% — carregue agora!"
                    else:
                        title = f"Bateria baixa — {dev.label}"
                        msg   = f"{pct}% de bateria restante."
                    _notify(title, msg)

        time.sleep(POLL_SECONDS)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _tray_icon

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    for dev, read_fn in zip(DEVICES, READERS):
        threading.Thread(
            target=_run_device,
            args=(dev, read_fn),
            daemon=True,
            name=f"monitor-{dev.label}",
        ).start()

    _tray_icon = pystray.Icon(
        name="battery_monitor",
        icon=_make_icon(None),
        title="Battery Monitor",
        menu=_build_menu(),
    )
    log.info("Battery Monitor started — check the system tray.")
    _tray_icon.run()


if __name__ == "__main__":
    main()
