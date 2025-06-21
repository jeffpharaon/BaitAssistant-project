# executor.py  (добавлена **ТОЛЬКО** логика «снимок-экрана»)
import os
import platform
import subprocess
import logging
import webbrowser
import winreg
import difflib
import psutil
import ctypes
import shutil
import speedtest
import screen_brightness_control as sbc
from win32com.client import Dispatch
from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import quote_plus

# ───────── screenshot ──────────────────────────────────────────────────────────
from PIL import ImageGrab           # pip install pillow
# ────────────────────────────────────────────────────────────────────────────────

# ───────── напоминания ─────────────────────────────────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler
from win10toast import ToastNotifier

_scheduler = BackgroundScheduler(daemon=True)
_scheduler.start()
_toast_notifier = ToastNotifier()
# ────────────────────────────────────────────────────────────────────────────────

from config import COMMANDS, APP_MAP          # ваши карты команд и приложений

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_app_index = None

VkNext, VkPrev, VkPlayPause = 0xB0, 0xB1, 0xB3
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002


def is_windows() -> bool:
    return platform.system().lower().startswith("win")


# ═════════════ поиск и запуск приложений ══════════════════════════════════════
def build_app_index() -> dict:
    global _app_index
    if _app_index is not None:
        return _app_index

    apps: dict[str, str] = {}

    # 1) App Paths из реестра
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
        except FileNotFoundError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            sub = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, sub) as subkey:
                try:
                    path, _ = winreg.QueryValueEx(subkey, None)
                    apps[os.path.splitext(sub.lower())[0]] = path
                except Exception:
                    pass

    # 2) ярлыки в меню «Пуск»
    shell = Dispatch("WScript.Shell")
    start_dirs = [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    ]
    for base in start_dirs:
        for root, _, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith(".lnk"):
                    name = os.path.splitext(fn)[0].lower()
                    try:
                        target = shell.CreateShortcut(os.path.join(root, fn)).Targetpath
                        if target:
                            apps[name] = target
                    except Exception:
                        pass

    # 3) ручные переопределения
    apps.update(APP_MAP)
    _app_index = apps
    return apps


def find_app_path(name: str) -> Optional[str]:
    apps = build_app_index()
    key = name.lower().strip()
    if key in apps:
        return apps[key]
    prefixes = [k for k in apps if k.startswith(key)]
    if prefixes:
        return apps[min(prefixes, key=len)]
    contains = [k for k in apps if key in k]
    if contains:
        return apps[min(contains, key=len)]
    matches = difflib.get_close_matches(key, apps.keys(), n=1, cutoff=0.7)
    return apps[matches[0]] if matches else None


# ═════════════ питание ═════════════════════════════════════════════════════════
def shutdown():
    cmd = ["shutdown", "/s", "/t", "0"] if is_windows() else ["shutdown", "-h", "now"]
    subprocess.check_call(cmd, shell=is_windows())
    log.info("Shutdown executed")


def restart():
    cmd = ["shutdown", "/r", "/t", "0"] if is_windows() else ["shutdown", "-r", "now"]
    subprocess.check_call(cmd, shell=is_windows())
    log.info("Restart executed")


# ═════════════ программы open/close ═══════════════════════════════════════════
def open_app(app_name: str):
    low = app_name.lower().strip()
    if low == "яндекс":
        low, app_name = "yandex", "yandex"
    if low in ("браузер", "browser", "интернет", "сеть"):
        os.startfile("http://") if is_windows() else webbrowser.open("http://")
        log.info("Opened default browser")
        return
    if is_windows() and low in ("проводник", "explorer"):
        subprocess.Popen(["explorer"], shell=True)
        log.info("Opened Explorer")
        return

    path = find_app_path(app_name)
    if not path:
        raise FileNotFoundError(f"App '{app_name}' not found")
    subprocess.Popen([path])
    log.info("Open %s -> %s", app_name, path)


def close_app(app_name: str):
    low = app_name.lower().strip()
    if low == "яндекс":
        low, app_name = "yandex", "yandex"
    if is_windows() and low in ("проводник", "explorer"):
        subprocess.call(["taskkill", "/F", "/IM", "explorer.exe"], shell=True)
        log.info("Closed Explorer")
        return
    if is_windows() and low in ("браузер", "browser", "интернет", "сеть"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"http\shell\open\command") as k:
                cmd, _ = winreg.QueryValueEx(k, None)
            import re
            m = re.match(r'"([^"]+)"', cmd)
            exe = m.group(1) if m else cmd.split()[0]
            proc_name = os.path.splitext(os.path.basename(exe))[0]
            for p in psutil.process_iter(["name"]):
                if p.info["name"] and p.info["name"].lower() == proc_name.lower():
                    p.kill()
            log.info("Closed browser: %s", proc_name)
        except Exception as e:
            log.error("Failed to close browser: %s", e)
        return

    path = find_app_path(app_name)
    if path:
        norm = os.path.normcase(os.path.abspath(path))
        killed = False
        for p in psutil.process_iter(["exe"]):
            if p.info.get("exe") and os.path.normcase(p.info["exe"]) == norm:
                p.kill()
                killed = True
        if killed:
            log.info("Closed %s by path", app_name)
        else:
            log.warning("No match to close %s", app_name)
    else:
        subprocess.call(["taskkill", "/F", "/IM", f"{app_name}.exe"], shell=True)
        log.info("Closed by name fallback: %s", app_name)


# ═════════════ мультимедиа / звук ═════════════════════════════════════════════
def media_key(vk: int):
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def media_next():         media_key(VkNext)
def media_prev():         media_key(VkPrev)
def media_play_pause():   media_key(VkPlayPause)


def _endpoint_vol():
    dev = AudioUtilities.GetSpeakers()
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def volume_up(step: int = 5):
    vol = _endpoint_vol()
    cur = vol.GetMasterVolumeLevelScalar()
    vol.SetMasterVolumeLevelScalar(min(1.0, cur + step / 100.0), None)
    log.info("Volume +%d%%", step)


def volume_down(step: int = 5):
    vol = _endpoint_vol()
    cur = vol.GetMasterVolumeLevelScalar()
    vol.SetMasterVolumeLevelScalar(max(0.0, cur - step / 100.0), None)
    log.info("Volume -%d%%", step)


# ═════════════ файлы / прочие утилиты ═════════════════════════════════════════
def create_folder(folder: str):
    path = os.path.abspath(folder)
    os.makedirs(path, exist_ok=True)
    log.info("Created folder: %s", path)


def delete_file_or_folder(name: str):
    path = os.path.abspath(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} does not exist")
    shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    log.info("Deleted: %s", path)


def zip_folder(folder: str):
    path = os.path.abspath(folder)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"{path} is not a folder")
    base, parent = os.path.basename(path), os.path.dirname(path)
    archive = shutil.make_archive(os.path.join(parent, base), "zip", path)
    log.info("Zipped %s -> %s", path, archive)


def search_file(name: str):
    home = os.path.expanduser("~")
    for root, _, files in os.walk(home):
        for f in files:
            if name.lower() in f.lower():
                full = os.path.join(root, f)
                if is_windows():
                    subprocess.Popen(["explorer", "/select,", full], shell=True)
                else:
                    subprocess.Popen(["xdg-open", root])
                log.info("Found and highlighted: %s", full)
                return
    raise FileNotFoundError(f"No file containing '{name}' found")


# ═════════════ speed-test (с результатом для UI) ═══════════════════════════════
_last_speed: tuple[float, float, float] | None = None      # ↓, ↑, ping
_last_speed_summary: str = ""


def get_last_speed() -> str:
    """
    Вызывается сервером чтобы показать результат во фронтэнде.
    """
    return _last_speed_summary or "Speed-test ещё не запускался"


def speed_test() -> tuple[float, float, float]:
    global _last_speed, _last_speed_summary

    st = speedtest.Speedtest()
    st.get_best_server()
    down = st.download() / 1e6
    up = st.upload() / 1e6
    ping = st.results.ping

    _last_speed = (down, up, ping)
    _last_speed_summary = f"Скорость: ↓ {down:.1f} Мбит/с, ↑ {up:.1f} Мбит/с, ping {ping:.0f} мс"
    log.info(_last_speed_summary)
    return _last_speed


# ═════════════ скриншот ═══════════════════════════════════════════════════════
def take_screenshot() -> str:
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(desktop, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(desktop, f"screenshot_{ts}.png")
    ImageGrab.grab().save(path, "PNG")
    log.info("Screenshot saved: %s", path)
    return path


# ═════════════ поиск в интернете ══════════════════════════════════════════════
def search_web(query: str):
    if not query:
        raise ValueError("Пустой поисковый запрос")
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    log.info("Web search: %s", query)


# ═════════════ звук / яркость / устройства ════════════════════════════════════
def switch_output_device(device: str):
    subprocess.call(["nircmd.exe", "setdefaultsounddevice", device, "0"], shell=True)
    log.info("Switched output to %s", device)


def switch_input_device(device: str):
    subprocess.call(["nircmd.exe", "setdefaultsounddevice", device, "1"], shell=True)
    log.info("Switched input to %s", device)


def brightness_up(step: int = 10):
    cur = sbc.get_brightness()[0]
    sbc.set_brightness(min(100, cur + step))
    log.info("Brightness +%d%% -> %d%%", step, min(100, cur + step))


def brightness_down(step: int = 10):
    cur = sbc.get_brightness()[0]
    sbc.set_brightness(max(0, cur - step))
    log.info("Brightness -%d%% -> %d%%", step, max(0, cur - step))


def set_brightness(level: int):
    sbc.set_brightness(level)
    log.info("Set brightness to %d%%", level)


# ═════════════ напоминания ════════════════════════════════════════════════════
def _toast(text: str):
    try:
        _toast_notifier.show_toast("Напоминание", text, duration=8, threaded=True)
    except Exception:
        log.info("TOAST: %s", text)


def _schedule(dt: datetime, text: str):
    _scheduler.add_job(_toast, "date", run_date=dt, args=[text], misfire_grace_time=60)
    log.info("Reminder scheduled: %s -> %s", dt, text)


def set_reminder(task: str, *, n: str = "", time: str = ""):
    when: datetime | None = None
    if n:
        when = datetime.now() + timedelta(minutes=int(n))
    elif time:
        h, m = map(int, time.split(":")[:2])
        when = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        if when <= datetime.now():
            when += timedelta(days=1)
    else:
        raise ValueError("Не указано время для напоминания")
    _schedule(when, task or "Напоминание")
    return when


def cancel_reminder():
    _scheduler.remove_all_jobs()
    log.info("All reminders cancelled")


# ═════════════ DISPATCHER ═════════════════════════════════════════════════════
def execute(intent: str, **kwargs) -> bool:
    try:
        if intent == "shutdown":
            shutdown()
        elif intent == "restart":
            restart()
        elif intent == "open_app":
            open_app(kwargs.get("app", ""))
        elif intent == "close_app":
            close_app(kwargs.get("app", ""))
        elif intent == "volume_up":
            volume_up(int(kwargs.get("level") or kwargs.get("n") or 5))
        elif intent == "volume_down":
            volume_down(int(kwargs.get("level") or kwargs.get("n") or 5))
        elif intent == "next_track":
            media_next()
        elif intent == "previous_track":
            media_prev()
        elif intent in ("play_music", "pause_music"):
            media_play_pause()
        elif intent == "speedtest":
            speed_test()
        elif intent == "create_folder":
            create_folder(kwargs.get("folder", ""))
        elif intent in ("delete_file", "delete_folder"):
            delete_file_or_folder(kwargs.get("file", kwargs.get("folder", "")))
        elif intent == "zip_folder":
            zip_folder(kwargs.get("folder", ""))
        elif intent == "search_file":
            search_file(kwargs.get("file", ""))
        elif intent == "search_web":
            search_web(kwargs.get("query", ""))
        elif intent == "screenshot":
            take_screenshot()
        elif intent == "switch_output":
            switch_output_device(kwargs.get("device", ""))
        elif intent == "switch_input":
            switch_input_device(kwargs.get("device", ""))
        elif intent == "brightness_up":
            brightness_up(int(kwargs.get("level") or kwargs.get("n") or 10))
        elif intent == "brightness_down":
            brightness_down(int(kwargs.get("level") or kwargs.get("n") or 10))
        elif intent == "set_brightness":
            set_brightness(int(kwargs.get("level") or 0))
        elif intent == "set_reminder":
            set_reminder(
                kwargs.get("task", ""),
                n=str(kwargs.get("n", "")),
                time=str(kwargs.get("time", "")),
            )
        elif intent == "cancel_reminder":
            cancel_reminder()
        else:
            return False
        return True
    except Exception as exc:
        log.error("execute(%s) failed: %s", intent, exc)
        return False