"""
Battery Monitor — System Tray App

Monitors Attack Shark X6 mouse, K86 keyboard, and Logitech G PRO X 2 headset.
Notifies at 25%, 10%, 5%, 1% per device via native Windows toast notifications.

CLI flags (EXE or script):
  --install     Copy to install dir, register startup task, launch
  --uninstall   Remove startup task and stop running instance
  (no flags)    Run the tray app
"""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

import mouse_battery
import keyboard_battery
import headset_battery

# ── Paths ─────────────────────────────────────────────────────────────────────

_FROZEN = getattr(sys, "frozen", False)

# When frozen: executable is the .exe itself.
# When running as script: use the script's directory.
_THIS_EXE = Path(sys.executable) if _FROZEN else Path(sys.argv[0]).resolve()

INSTALL_DIR  = Path(r"D:\Program Files (x86)\BatteryMonitor")
INSTALL_EXE  = INSTALL_DIR / "BatteryMonitor.exe"
_TASK_NAME   = "BatteryMonitor"

# PID file lives next to the running EXE so --install can find and stop it
_PID_FILE = (_THIS_EXE.parent / "BatteryMonitor.pid") if _FROZEN \
            else (Path(__file__).parent / "tray_app.pid")

log = logging.getLogger("battery_monitor")

# ── Config ────────────────────────────────────────────────────────────────────

THRESHOLDS   = [25, 10, 5, 1]
POLL_SECONDS = 60


# ── Notification ──────────────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    log.info("NOTIFY  %s — %s", title, message)
    try:
        from winotify import Notification
        Notification(app_id="Battery Monitor", title=title,
                     msg=message, duration="short").show()
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
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    c   = _battery_color(pct)

    d.rectangle([4, 16, 54, 52], outline=c, width=3)
    d.rectangle([54, 28, 60, 40], fill=c)

    if pct is not None and pct > 0:
        fill_w = max(1, int(46 * pct / 100))
        d.rectangle([7, 19, 7 + fill_w, 49], fill=c)

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
    _pid_remove()
    icon.stop()


# ── PID file ──────────────────────────────────────────────────────────────────

def _pid_write() -> None:
    try:
        _PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def _pid_remove() -> None:
    try:
        _PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _pid_stop(pid_file: Path) -> None:
    """Kill the process recorded in pid_file, then delete it."""
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True)
        time.sleep(1.5)
    except Exception:
        pass
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass


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


# ── Tray app entry point ──────────────────────────────────────────────────────

def main() -> None:
    global _tray_icon

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    _pid_write()

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
    log.info("Battery Monitor started.")
    _tray_icon.run()


# ── Install / Uninstall ───────────────────────────────────────────────────────

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevate_and_rerun() -> None:
    """Re-launch the current process with admin privileges."""
    args = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(_THIS_EXE), args, None, 1
    )
    sys.exit(0)


def _schtasks(*args: str) -> bool:
    result = subprocess.run(["schtasks", *args], capture_output=True)
    return result.returncode == 0


def cmd_install() -> None:
    """Copy this EXE to INSTALL_DIR, register startup task, and launch."""
    if not _is_admin():
        print("Requesting admin rights for install...")
        _elevate_and_rerun()
        return

    installed_pid = INSTALL_DIR / "BatteryMonitor.pid"
    if installed_pid.exists():
        print("Stopping running instance...")
        _pid_stop(installed_pid)

    print(f"Creating directory: {INSTALL_DIR}")
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Copying: {_THIS_EXE}  →  {INSTALL_EXE}")
    shutil.copy2(_THIS_EXE, INSTALL_EXE)

    ok = _schtasks(
        "/create",
        "/tn",    _TASK_NAME,
        "/sc",    "ONLOGON",
        "/tr",    f'"{INSTALL_EXE}"',
        "/delay", "0000:30",
        "/f",
    )
    if ok:
        print(f'Startup task "{_TASK_NAME}" registered.')
    else:
        print("WARNING: Failed to register startup task.")

    print("Launching Battery Monitor...")
    subprocess.Popen(
        [str(INSTALL_EXE)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    print("Done.")


def cmd_uninstall() -> None:
    """Remove startup task and stop the running instance."""
    if not _is_admin():
        print("Requesting admin rights for uninstall...")
        _elevate_and_rerun()
        return

    print("Stopping running instance...")
    _pid_stop(INSTALL_DIR / "BatteryMonitor.pid")

    if _schtasks("/delete", "/tn", _TASK_NAME, "/f"):
        print(f'Startup task "{_TASK_NAME}" removed.')
    else:
        print(f'Task "{_TASK_NAME}" not found (already removed?).')

    print(f"Files kept at: {INSTALL_DIR}")
    print("Delete the folder manually if you want a full cleanup.")


# ── CLI entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Battery Monitor — Attack Shark X6 / K86, Logitech G PRO X 2"
    )
    parser.add_argument("--install",   action="store_true",
                        help=f"Install to {INSTALL_DIR} and register startup task")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove startup task and stop running instance")
    args = parser.parse_args()

    if args.install:
        cmd_install()
    elif args.uninstall:
        cmd_uninstall()
    else:
        main()
