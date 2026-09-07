"""
ZapretManager - Common utility functions
"""

import csv
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from io import StringIO

from .config import (
    APP_NAME,
    MUTEX_NAME,
    DEFAULT_ROOT_DIR,
    APPDATA_DIR,
    CONFIG_FILE,
    HIDDEN_WINDOW_FLAG,
    STARTF_USESHOWWINDOW,
    SW_HIDE,
    PING_ATTEMPTS,
    PING_INTERVAL,
    PING_TIMEOUT,
    PROCESS_STOP_TIMEOUT,
    WINWS_POLL_INTERVAL,
    mutex_handle,
    mutex_released,
)


def ensure_config_directory():
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
    except OSError:
        pass


def load_config():
    ensure_config_directory()

    config = {
        "root_dir": DEFAULT_ROOT_DIR
    }

    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict) and data.get("root_dir"):
                config["root_dir"] = data["root_dir"]

        except Exception:
            pass

    return config


def save_config(root_dir):
    ensure_config_directory()

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"root_dir": root_dir},
                f,
                ensure_ascii=False,
                indent=4,
            )
    except Exception as exc:
        print(f"Ошибка сохранения конфигурации: {exc}")


def create_no_window_startupinfo():
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE
    return startupinfo


def run_hidden(command, *, cwd=None, timeout=30, check=False):
    return subprocess.run(
        command,
        cwd=cwd,
        creationflags=HIDDEN_WINDOW_FLAG,
        startupinfo=create_no_window_startupinfo(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def launch_as_admin():
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            params = " ".join(
                f'"{arg}"'
                for arg in sys.argv[1:]
            )
        else:
            executable = sys.executable
            params = " ".join(
                [f'"{sys.argv[0]}"']
                + [f'"{arg}"' for arg in sys.argv[1:]]
            )

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            None,
            1,
        )

        return result > 32

    except Exception:
        return False


def check_tcp_ping(host, port=443, timeout=None, attempts=None):
    timeout = PING_TIMEOUT if timeout is None else timeout
    attempts = PING_ATTEMPTS if attempts is None else attempts

    values = []

    for _ in range(attempts):
        try:
            started = time.perf_counter()

            sock = socket.create_connection(
                (host, port),
                timeout=timeout,
            )

            sock.close()

            values.append(
                (time.perf_counter() - started) * 1000
            )

        except Exception:
            pass

        time.sleep(PING_INTERVAL)

    if not values:
        return None

    values.sort()

    return round(values[len(values) // 2])


def get_winws_pids():
    pids = []

    try:
        result = run_hidden(
            [
                "tasklist",
                "/FI",
                "IMAGENAME eq winws.exe",
                "/FO",
                "CSV",
            ],
            timeout=10,
        )

        reader = csv.reader(StringIO(result.stdout))
        next(reader, None)

        for row in reader:
            if len(row) >= 2 and row[1].isdigit():
                pids.append(int(row[1]))

    except Exception:
        pass

    return pids


def is_winws_running():
    return bool(get_winws_pids())


def kill_process_by_pid(pid):
    if not pid:
        return False

    try:
        result = run_hidden(
            [
                "taskkill",
                "/F",
                "/PID",
                str(pid),
            ],
            timeout=10,
        )

        return result.returncode == 0

    except Exception:
        return False


def kill_winws():
    try:
        result = run_hidden(
            [
                "taskkill",
                "/F",
                "/IM",
                "winws.exe",
            ],
            timeout=10,
        )

        return result.returncode in (0, 128)

    except Exception:
        return False


def wait_until_no_winws(timeout=PROCESS_STOP_TIMEOUT):
    end = time.monotonic() + timeout

    while time.monotonic() < end:
        if not is_winws_running():
            return True

        time.sleep(WINWS_POLL_INTERVAL)

    return not is_winws_running()


def get_resource_path(relative_path):
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base, relative_path)


def create_mutex():
    global mutex_handle

    mutex_handle = ctypes.windll.kernel32.CreateMutexW(
        None,
        False,
        MUTEX_NAME,
    )

    if not mutex_handle:
        return True, None

    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == 183:
        return False, mutex_handle

    return True, mutex_handle


def release_mutex():
    global mutex_handle, mutex_released

    if mutex_released:
        return

    if mutex_handle:
        ctypes.windll.kernel32.CloseHandle(mutex_handle)
        mutex_handle = None
        mutex_released = True


def activate_existing_window():
    hwnd = ctypes.windll.user32.FindWindowW(
        None,
        APP_NAME,
    )

    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)


def normalize_bat_name(name):
    return os.path.splitext(
        os.path.basename(name)
    )[0]
