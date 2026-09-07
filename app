import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import subprocess
import ctypes
import sys
import threading
import socket
import time
import json
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import csv
from io import StringIO
import queue
import winreg

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

APP_NAME = "ZapretManager"
MUTEX_NAME = "ZapretManager_Mutex"

DEFAULT_ROOT_DIR = r"D:\Games\zapret\ALL_VERSIONS"
DEFAULT_HIDDEN = False

APPDATA_DIR = os.path.join(
    os.getenv("APPDATA") or os.path.expanduser("~"),
    APP_NAME
)

CONFIG_FILE = os.path.join(
    APPDATA_DIR,
    "zapret_config.json"
)

HIDDEN_WINDOW_FLAG = 0x08000000  # CREATE_NO_WINDOW
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0

# Таймауты и параметры тестирования (вынесены в константы)
WINWS_START_TIMEOUT = 5.0  # секунд на ожидание появления winws.exe
WINWS_POLL_INTERVAL = 0.25  # интервал опроса PID
PROCESS_STOP_TIMEOUT = 3.0  # секунд на ожидание завершения процесса
PING_ATTEMPTS = 3  # количество попыток TCP-подключения
PING_INTERVAL = 0.2  # интервал между попытками ping
PING_TIMEOUT = 2.0  # таймаут одного подключения

# Глобальная переменная для хранения хэндла мьютекса
mutex_handle = None
mutex_released = False

# Очередь для безопасной связи между tray thread и GUI thread
tray_command_queue = queue.Queue()

# ============================================================
# МЕНЕДЖЕР СЕРВИСОВ (перенос логики service.bat в Python)
# ============================================================

SERVICE_NAME = "zapret"
SERVICE_DISPLAY_NAME = "zapret"
SERVICE_DESCRIPTION = "Zapret DPI bypass software"


class ServiceManager:
    """Управление сервисом Windows для zapret."""
    
    @staticmethod
    def is_admin():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    
    @staticmethod
    def run_as_admin(script_path=None):
        """Запускает текущий скрипт от администратора."""
        try:
            if getattr(sys, "frozen", False):
                executable = sys.executable
                params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
            else:
                executable = sys.executable
                params = " ".join([f'"{sys.argv[0]}"'] + [f'"{arg}"' for arg in sys.argv[1:]])
            
            ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
            return True
        except Exception:
            return False
    
    @staticmethod
    def check_service_exists(service_name=SERVICE_NAME):
        """Проверяет, существует ли сервис."""
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=10
            )
            # ERROR_SERVICE_DOES_NOT_EXIST = 1060
            if result.returncode == 1060:
                return False
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_service_status(service_name=SERVICE_NAME):
        """
        Возвращает статус сервиса.
        Возвращает: None (не существует), "RUNNING", "STOPPED", "STOP_PENDING", "START_PENDING", или другое
        """
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return None
            
            for line in result.stdout.splitlines():
                if "STATE" in line.upper():
                    # Пример: "        STATE              : 4  RUNNING"
                    parts = line.split(":")
                    if len(parts) >= 2:
                        status = parts[1].strip().split()[0]
                        return status
            return "UNKNOWN"
        except Exception:
            return None
    
    @staticmethod
    def get_service_strategy(service_name=SERVICE_NAME):
        """Получает стратегию из реестра."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                f"System\\CurrentControlSet\\Services\\{service_name}",
                0,
                winreg.KEY_READ
            )
            try:
                strategy, _ = winreg.QueryValueEx(key, "zapret-discord-youtube")
                winreg.CloseKey(key)
                return strategy
            except FileNotFoundError:
                winreg.CloseKey(key)
                return None
        except Exception:
            return None
    
    @staticmethod
    def set_service_strategy(strategy, service_name=SERVICE_NAME):
        """Устанавливает стратегию в реестр."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                f"System\\CurrentControlSet\\Services\\{service_name}",
                0,
                winreg.KEY_WRITE
            )
            try:
                winreg.SetValueEx(key, "zapret-discord-youtube", 0, winreg.REG_SZ, strategy)
                winreg.CloseKey(key)
                return True
            except Exception:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False
    
    @staticmethod
    def install_service(bin_path, args, service_name=SERVICE_NAME):
        """
        Устанавливает сервис.
        bin_path: путь к winws.exe
        args: аргументы командной строки
        Возвращает: (success, message)
        """
        try:
            # Удаляем старый сервис если существует
            ServiceManager.delete_service(service_name)
            
            # Создаём сервис
            binpath = f'"{bin_path}" {args}'
            result = subprocess.run(
                ["sc", "create", service_name, "binPath=", binpath, "DisplayName=", SERVICE_DISPLAY_NAME, "start=", "auto"],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"Ошибка создания сервиса: {result.stderr}"
            
            # Устанавливаем описание
            subprocess.run(
                ["sc", "description", service_name, SERVICE_DESCRIPTION],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Проверяем что сервис создан
            if not ServiceManager.check_service_exists(service_name):
                return False, "Сервис не появился после создания"
            
            return True, "Сервис успешно установлен"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    
    @staticmethod
    def delete_service(service_name=SERVICE_NAME):
        """
        Удаляет сервис.
        Возвращает: (success, message)
        """
        try:
            # Сначала останавливаем
            ServiceManager.stop_service(service_name)
            time.sleep(0.5)
            
            result = subprocess.run(
                ["sc", "delete", service_name],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Проверяем результат
            time.sleep(0.5)
            if ServiceManager.check_service_exists(service_name):
                return False, "Не удалось удалить сервис"
            
            return True, "Сервис успешно удалён"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    
    @staticmethod
    def start_service(service_name=SERVICE_NAME):
        """
        Запускает сервис.
        Возвращает: (success, message)
        """
        try:
            result = subprocess.run(
                ["sc", "start", service_name],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                # Проверяем, может уже запущен
                status = ServiceManager.get_service_status(service_name)
                if status == "RUNNING":
                    return True, "Сервис уже запущен"
                return False, f"Ошибка запуска: {result.stderr}"
            
            # Ждём запуска
            for _ in range(20):
                time.sleep(0.25)
                status = ServiceManager.get_service_status(service_name)
                if status == "RUNNING":
                    return True, "Сервис успешно запущен"
                if status not in ("START_PENDING", None):
                    break
            
            return False, "Сервис не перешёл в состояние RUNNING"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    
    @staticmethod
    def stop_service(service_name=SERVICE_NAME):
        """
        Останавливает сервис.
        Возвращает: (success, message)
        """
        try:
            status = ServiceManager.get_service_status(service_name)
            if status == "STOPPED":
                return True, "Сервис уже остановлен"
            if status is None:
                return False, "Сервис не существует"
            
            result = subprocess.run(
                ["sc", "stop", service_name],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"Ошибка остановки: {result.stderr}"
            
            # Ждём остановки
            for _ in range(20):
                time.sleep(0.25)
                status = ServiceManager.get_service_status(service_name)
                if status == "STOPPED":
                    return True, "Сервис успешно остановлен"
                if status not in ("STOP_PENDING", "RUNNING", None):
                    break
            
            return False, "Сервис не перешёл в состояние STOPPED"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
    
    @staticmethod
    def restart_service(service_name=SERVICE_NAME):
        """Перезапускает сервис."""
        success, msg = ServiceManager.stop_service(service_name)
        if not success:
            return False, msg
        time.sleep(1)
        return ServiceManager.start_service(service_name)
    
    @staticmethod
    def is_winws_running():
        """Проверяет, запущен ли winws.exe."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq winws.exe"],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True
            )
            return "winws.exe" in result.stdout.lower()
        except Exception:
            return False
    
    @staticmethod
    def kill_winws():
        """Убивает все процессы winws.exe."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "winws.exe"],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True
            )
            return True
        except Exception:
            return False

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def ensure_config_directory():
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
    except Exception:
        pass

def load_config():
    ensure_config_directory()
    config = {"root_dir": DEFAULT_ROOT_DIR, "run_bat_hidden": DEFAULT_HIDDEN}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
            if "root_dir" in data:
                config["root_dir"] = data["root_dir"]
            if "run_bat_hidden" in data:
                config["run_bat_hidden"] = data["run_bat_hidden"]
        except Exception:
            pass
    return config

def save_config(root_dir, run_bat_hidden):
    ensure_config_directory()
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump({
                "root_dir": root_dir,
                "run_bat_hidden": run_bat_hidden
            }, file, ensure_ascii=False, indent=4)
    except Exception as error:
        print(f"Ошибка сохранения конфигурации: {error}")

def check_tcp_ping(host, port=443, timeout=None, attempts=None):
    """Измеряет TCP-пинг до хоста, возвращает медиану в мс или None при ошибке."""
    if timeout is None:
        timeout = PING_TIMEOUT
    if attempts is None:
        attempts = PING_ATTEMPTS
    
    results = []
    for _ in range(attempts):
        try:
            start = time.perf_counter()
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            results.append((time.perf_counter() - start) * 1000)
        except Exception:
            continue
        time.sleep(PING_INTERVAL)
    if not results:
        return None
    results.sort()
    return round(results[len(results) // 2])

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def kill_winws():
    """Убивает все процессы winws.exe."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "winws.exe"],
            creationflags=HIDDEN_WINDOW_FLAG,
            capture_output=True,
            text=True
        )
        return True
    except Exception:
        return False

def is_winws_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe"],
            creationflags=HIDDEN_WINDOW_FLAG,
            capture_output=True,
            text=True
        )
        return "winws.exe" in result.stdout.lower()
    except Exception:
        return False

def get_winws_pids():
    """Возвращает список PID всех процессов winws.exe, используя csv."""
    pids = []
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV"],
            creationflags=HIDDEN_WINDOW_FLAG,
            capture_output=True,
            text=True
        )
        reader = csv.reader(StringIO(result.stdout))
        next(reader, None)  # пропускаем заголовок
        for row in reader:
            if len(row) >= 2:
                pid_str = row[1].strip()
                if pid_str.isdigit():
                    pids.append(int(pid_str))
    except Exception:
        pass
    return pids

def kill_process_by_pid(pid):
    """Убивает процесс по PID, возвращает True если успешно."""
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            creationflags=HIDDEN_WINDOW_FLAG,
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False

def wait_for_process_exit(pid, timeout=None):
    """Ожидает завершения процесса с заданным PID, возвращает True если он исчез."""
    if timeout is None:
        timeout = PROCESS_STOP_TIMEOUT
    if pid is None:
        return True
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Проверяем через tasklist с фильтром по PID
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                creationflags=HIDDEN_WINDOW_FLAG,
                capture_output=True,
                text=True
            )
            # Если PID нет в выводе, процесс исчез
            if str(pid) not in result.stdout:
                return True
        except Exception:
            pass
        time.sleep(WINWS_POLL_INTERVAL)
    return False

def wait_until_no_winws(timeout=None):
    """Ожидает, пока все winws.exe завершатся."""
    if timeout is None:
        timeout = PROCESS_STOP_TIMEOUT
    start = time.time()
    while time.time() - start < timeout:
        if not is_winws_running():
            return True
        time.sleep(WINWS_POLL_INTERVAL)
    return False

# ============================================================
# УПРАВЛЕНИЕ ЕДИНСТВЕННЫМ ЭКЗЕМПЛЯРОМ
# ============================================================

def create_mutex():
    global mutex_handle
    mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex_handle:
        return True, None
    last_error = ctypes.windll.kernel32.GetLastError()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
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
    hwnd = ctypes.windll.user32.FindWindowW(None, APP_NAME)
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)

# ============================================================
# ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ============================================================

class ZapretLauncher(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.root_dir = self.config.get("root_dir", DEFAULT_ROOT_DIR)
        self.run_bat_hidden = self.config.get("run_bat_hidden", DEFAULT_HIDDEN)

        self.selected_version = ctk.StringVar(value="")
        self.selected_bat = ctk.StringVar(value="")

        self.version_buttons = {}
        self.bat_buttons = {}

        self.versions_data = {}
        self.bat_ping_results = {}   # bat_name -> {"youtube": ms or None, "discord": ms or None}

        self.tray_icon = None
        self.icon_image = None
        self.temp_icon_path = None
        self.protection_starting = False
        self.testing_all = False
        self.stop_requested = False   # флаг для прерывания массового теста
        self.stopping = False
        self.closing = False

        # Events для синхронизации потоков
        self.shutdown_event = threading.Event()  # сигнал полного завершения приложения
        self.test_cancel_event = threading.Event()  # сигнал отмены текущего теста

        # PID управляемого процесса (для обычного режима)
        # Теперь хранит список PID, а не один PID
        self.managed_pids = set()

        # Окно
        self.title(APP_NAME)
        self.geometry("620x740")
        self.resizable(False, False)
        self.configure(fg_color="#121318")

        self.create_interface()
        self.update_window_icon()
        self.render_versions_list()

        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.setup_tray()

    # ========================================================
    # ИНТЕРФЕЙС
    # ========================================================

    def create_interface(self):

        # HEADER
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent", height=32)
        self.header_frame.pack(fill="x", padx=16, pady=(14, 10))

        self.logo_label = ctk.CTkLabel(
            self.header_frame,
            text=" Zapret Multi-Manager",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#FFFFFF"
        )
        self.logo_label.pack(side="left")

        self.settings_btn = ctk.CTkButton(
            self.header_frame,
            text="⚙",
            width=28,
            height=28,
            fg_color="transparent",
            hover_color="#1E2029",
            text_color="#9CA3AF",
            font=ctk.CTkFont(size=16),
            command=self.show_settings_menu
        )
        self.settings_btn.pack(side="right")

        # STATUS CARD
        self.status_card = ctk.CTkFrame(
            self,
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            corner_radius=10
        )
        self.status_card.pack(fill="x", padx=16, pady=(0, 10))

        self.status_title = ctk.CTkLabel(
            self.status_card,
            text="● ОСТАНОВЛЕНО",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#EF4444"
        )
        self.status_title.pack(anchor="w", padx=14, pady=(10, 2))

        self.status_sub = ctk.CTkLabel(
            self.status_card,
            text="Выберите версию и обход",
            font=ctk.CTkFont(size=11),
            text_color="#9CA3AF"
        )
        self.status_sub.pack(anchor="w", padx=14, pady=(0, 10))

        # PING CARD (для активного режима)
        self.ping_card = ctk.CTkFrame(
            self,
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            corner_radius=10
        )
        self.ping_card.pack(fill="x", padx=16, pady=(0, 10))

        self.ping_title_frame = ctk.CTkFrame(self.ping_card, fg_color="transparent")
        self.ping_title_frame.pack(fill="x", padx=14, pady=(8, 4))

        self.ping_card_title = ctk.CTkLabel(
            self.ping_title_frame,
            text="ПИНГ СЕРВЕРОВ (активный)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9CA3AF"
        )
        self.ping_card_title.pack(side="left")

        self.btn_check_ping = ctk.CTkButton(
            self.ping_title_frame,
            text="⚡ Проверить",
            width=80,
            height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2E3240",
            hover_color="#374151",
            text_color="#FFFFFF",
            corner_radius=6,
            command=self.run_ping_check
        )
        self.btn_check_ping.pack(side="right")

        self.ping_labels_frame = ctk.CTkFrame(self.ping_card, fg_color="transparent")
        self.ping_labels_frame.pack(fill="x", padx=14, pady=(0, 8))

        self.yt_ping_label = ctk.CTkLabel(
            self.ping_labels_frame,
            text="YouTube: -- ms",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9CA3AF"
        )
        self.yt_ping_label.pack(side="left", expand=True, anchor="w")

        self.dc_ping_label = ctk.CTkLabel(
            self.ping_labels_frame,
            text="Discord: -- ms",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9CA3AF"
        )
        self.dc_ping_label.pack(side="right", expand=True, anchor="e")

        # ----------------------------------------------------
        # ОСНОВНАЯ КАРТОЧКА С ДВУМЯ КОЛОНКАМИ
        # ----------------------------------------------------
        self.main_card = ctk.CTkFrame(
            self,
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            corner_radius=10
        )
        self.main_card.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Контейнер для двух колонок
        self.columns_frame = ctk.CTkFrame(self.main_card, fg_color="transparent")
        self.columns_frame.pack(fill="both", expand=True, padx=6, pady=(8, 4))

        # ЛЕВАЯ КОЛОНКА – ВЕРСИИ
        self.left_col = ctk.CTkFrame(self.columns_frame, fg_color="transparent")
        self.left_col.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.version_title = ctk.CTkLabel(
            self.left_col,
            text="ВЕРСИЯ ЗАПРЕТА",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9CA3AF"
        )
        self.version_title.pack(anchor="w", pady=(0, 4))

        self.version_scroll_frame = ctk.CTkScrollableFrame(
            self.left_col,
            fg_color="transparent",
            height=180,
            scrollbar_button_color="#2E3240",
            scrollbar_button_hover_color="#374151"
        )
        self.version_scroll_frame.pack(fill="both", expand=True)

        # ПРАВАЯ КОЛОНКА – BAT
        self.right_col = ctk.CTkFrame(self.columns_frame, fg_color="transparent")
        self.right_col.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Заголовок BAT с кнопкой теста всех
        self.bat_header_frame = ctk.CTkFrame(self.right_col, fg_color="transparent")
        self.bat_header_frame.pack(fill="x", pady=(0, 4))

        self.profile_title = ctk.CTkLabel(
            self.bat_header_frame,
            text="ОБХОД (.BAT)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9CA3AF"
        )
        self.profile_title.pack(side="left")

        self.btn_test_all = ctk.CTkButton(
            self.bat_header_frame,
            text="📊 Тест всех",
            width=90,
            height=22,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2E3240",
            hover_color="#374151",
            text_color="#FFFFFF",
            corner_radius=6,
            command=self.start_test_all
        )
        self.btn_test_all.pack(side="right")

        self.scroll_frame = ctk.CTkScrollableFrame(
            self.right_col,
            fg_color="transparent",
            height=180,
            scrollbar_button_color="#2E3240",
            scrollbar_button_hover_color="#374151"
        )
        self.scroll_frame.pack(fill="both", expand=True)

        # КНОПКА УПРАВЛЕНИЕ СЕРВИСОМ (под колонками, на всю ширину)
        self.btn_service = ctk.CTkButton(
            self.main_card,
            text="⚙ Управление сервисом",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#3B82F6",
            hover_color="#2563EB",
            text_color="#FFFFFF",
            height=36,
            corner_radius=6,
            command=self.open_service_manager
        )
        self.btn_service.pack(fill="x", padx=14, pady=(8, 8))

        # ----------------------------------------------------
        # КНОПКИ УПРАВЛЕНИЯ
        # ----------------------------------------------------
        self.buttons_container = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons_container.pack(fill="x", padx=16, pady=(0, 16))

        self.btn_start = ctk.CTkButton(
            self.buttons_container,
            text="Запуск",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#FFFFFF",
            height=42,
            corner_radius=8,
            command=self.start_process
        )
        self.btn_start.pack(fill="x", pady=(0, 8))

        self.btn_stop = ctk.CTkButton(
            self.buttons_container,
            text="Стоп",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1A1B23",
            border_color="#EF4444",
            border_width=1,
            hover_color="#2A1215",
            text_color="#EF4444",
            height=38,
            corner_radius=8,
            command=self.stop_process
        )
        self.btn_stop.pack(fill="x", pady=(0, 8))

        self.btn_quit = ctk.CTkButton(
            self.buttons_container,
            text="❌ Закрыть",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1A1B23",
            border_color="#EF4444",
            border_width=1,
            hover_color="#2A1215",
            text_color="#EF4444",
            height=36,
            corner_radius=8,
            command=self.quit_app
        )
        self.btn_quit.pack(fill="x")

    # ========================================================
    # ПАПКА
    # ========================================================

    def ask_for_folder(self):
        messagebox.showwarning(
            "Папка не найдена",
            f"Папка:\n\n{self.root_dir}\n\nне найдена.\n\nВыберите папку ALL_VERSIONS, в которой находятся версии Zapret."
        )
        folder = filedialog.askdirectory(title="Выберите папку ALL_VERSIONS")
        if folder:
            self.root_dir = folder
            save_config(self.root_dir, self.run_bat_hidden)
            self.selected_version.set("")
            self.selected_bat.set("")
            self.bat_ping_results.clear()
            self.render_versions_list()
            self.update_window_icon()
        else:
            if not os.path.exists(self.root_dir):
                self.status_sub.configure(text="Папка Zapret не выбрана")

    # ========================================================
    # ИКОНКА
    # ========================================================

    def load_icon(self):
        if not os.path.exists(self.root_dir):
            return self.create_default_icon()
        try:
            for item_name in os.listdir(self.root_dir):
                item_path = os.path.join(self.root_dir, item_name)
                if not os.path.isdir(item_path):
                    continue
                icon_path = os.path.join(item_path, "icon.ico")
                if os.path.exists(icon_path):
                    try:
                        return Image.open(icon_path).convert("RGBA")
                    except Exception:
                        pass
        except Exception:
            pass
        return self.create_default_icon()

    def create_default_icon(self):
        image = Image.new("RGB", (64, 64), (18, 19, 24))
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 48, 48), fill=(16, 185, 129))
        return image

    def update_window_icon(self):
        try:
            self.icon_image = self.load_icon()
            if not self.icon_image:
                return
            temp_dir = os.getenv("TEMP") or os.path.expanduser("~")
            self.temp_icon_path = os.path.join(temp_dir, "zapret_manager_icon.ico")
            self.icon_image.save(self.temp_icon_path, format="ICO")
            self.iconbitmap(self.temp_icon_path)
        except Exception:
            pass
        self.refresh_tray()

    # ========================================================
    # ВЕРСИИ
    # ========================================================

    def render_versions_list(self):
        for widget in self.version_scroll_frame.winfo_children():
            widget.destroy()
        self.version_buttons.clear()
        self.versions_data.clear()
        self.bat_ping_results.clear()

        if not os.path.isdir(self.root_dir):
            self.selected_version.set("")
            self.selected_bat.set("")
            label = ctk.CTkLabel(
                self.version_scroll_frame,
                text="Папка не найдена",
                text_color="#EF4444"
            )
            label.pack(pady=10)
            self.clear_bat_list()
            return

        found_versions = []
        try:
            root_items = os.listdir(self.root_dir)
        except Exception as error:
            label = ctk.CTkLabel(
                self.version_scroll_frame,
                text=f"Ошибка чтения папки:\n{error}",
                text_color="#EF4444"
            )
            label.pack(pady=10)
            return

        for item_name in sorted(root_items, key=str.lower):
            item_path = os.path.join(self.root_dir, item_name)
            if not os.path.isdir(item_path):
                continue
            try:
                bats = []
                for filename in os.listdir(item_path):
                    if not filename.lower().endswith(".bat"):
                        continue
                    if filename.lower().startswith("service"):
                        continue
                    bats.append(filename)
                bats.sort(key=str.lower)
                if bats:
                    found_versions.append(item_name)
                    self.versions_data[item_name] = bats
            except Exception:
                continue

        if not found_versions:
            self.selected_version.set("")
            self.selected_bat.set("")
            label = ctk.CTkLabel(
                self.version_scroll_frame,
                text="Версии не найдены",
                text_color="#F59E0B"
            )
            label.pack(pady=10)
            self.clear_bat_list()
            return

        current_version = self.selected_version.get()
        if current_version not in found_versions:
            current_version = found_versions[0]
            self.selected_version.set(current_version)
            self.selected_bat.set("")

        for version_name in found_versions:
            selected = (version_name == self.selected_version.get())
            button = ctk.CTkButton(
                self.version_scroll_frame,
                text=f"📂 {version_name}",
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold" if selected else "normal"),
                height=34,
                corner_radius=6,
                fg_color="#8B5CF6" if selected else "transparent",
                border_color="#8B5CF6" if selected else "#2E3240",
                border_width=1,
                text_color="#FFFFFF" if selected else "#9CA3AF",
                hover_color="#7C3AED" if selected else "#1E2029",
                command=lambda v=version_name: self.select_version(v)
            )
            button.pack(fill="x", pady=2)
            self.version_buttons[version_name] = button

        self.update_bat_list()
        self.refresh_tray()

    # ========================================================
    # ВЫБОР ВЕРСИИ
    # ========================================================

    def select_version(self, version_name):
        if self.testing_all:
            return
        if version_name not in self.versions_data:
            return
        self.selected_version.set(version_name)
        self.bat_ping_results.clear()

        bats = self.versions_data.get(version_name, [])
        if self.selected_bat.get() not in bats:
            self.selected_bat.set(bats[0] if bats else "")

        for name, button in self.version_buttons.items():
            selected = (name == version_name)
            button.configure(
                fg_color="#8B5CF6" if selected else "transparent",
                border_color="#8B5CF6" if selected else "#2E3240",
                text_color="#FFFFFF" if selected else "#9CA3AF",
                font=ctk.CTkFont(size=12, weight="bold" if selected else "normal"),
                hover_color="#7C3AED" if selected else "#1E2029"
            )

        self.update_bat_list()
        self.update_window_icon()
        self.status_sub.configure(text=f"Версия: {version_name} | Выберите обход")
        self.refresh_tray()

    # ========================================================
    # BAT-ФАЙЛЫ
    # ========================================================

    def clear_bat_list(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.bat_buttons.clear()

    def update_bat_list(self):
        self.clear_bat_list()
        version = self.selected_version.get()
        if not version:
            return
        bats = self.versions_data.get(version, [])
        if not bats:
            return
        if self.selected_bat.get() not in bats:
            self.selected_bat.set(bats[0])

        for bat_name in bats:
            selected = (bat_name == self.selected_bat.get())
            display_text = f"📄 {bat_name}"
            result = self.bat_ping_results.get(bat_name)
            if result:
                yt = result.get("youtube")
                dc = result.get("discord")
                yt_str = f"{yt} ms" if yt is not None else "❌"
                dc_str = f"{dc} ms" if dc is not None else "❌"
                display_text += f"   YouTube: {yt_str}   Discord: {dc_str}"
            button = ctk.CTkButton(
                self.scroll_frame,
                text=display_text,
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold" if selected else "normal"),
                height=34,
                corner_radius=6,
                fg_color="#10B981" if selected else "transparent",
                border_color="#10B981" if selected else "#2E3240",
                border_width=1,
                text_color="#FFFFFF" if selected else "#9CA3AF",
                hover_color="#059669" if selected else "#1E2029",
                command=lambda b=bat_name: self.select_bat(b)
            )
            button.pack(fill="x", pady=2)
            self.bat_buttons[bat_name] = button

        self.refresh_tray()

    # ========================================================
    # ВЫБОР BAT
    # ========================================================

    def select_bat(self, bat_name):
        if self.testing_all:
            return
        if bat_name not in self.bat_buttons:
            return
        self.selected_bat.set(bat_name)

        for name, button in self.bat_buttons.items():
            selected = (name == bat_name)
            button.configure(
                fg_color="#10B981" if selected else "transparent",
                border_color="#10B981" if selected else "#2E3240",
                text_color="#FFFFFF" if selected else "#9CA3AF",
                font=ctk.CTkFont(size=12, weight="bold" if selected else "normal"),
                hover_color="#059669" if selected else "#1E2029"
            )

        version = self.selected_version.get()
        self.status_sub.configure(text=f"Версия: {version} | Обход: {bat_name}")
        self.refresh_tray()

    # ========================================================
    # ЕДИНЫЙ МЕТОД ТЕСТИРОВАНИЯ ОДНОГО BAT
    # ========================================================

    def test_single_bat(self, version_path, bat_name, progress_callback=None):
        """
        ЕДИНСТВЕННЫЙ алгоритм проверки BAT.

        Схема:
            1. Фиксируем старые winws.exe
            2. Удаляем старые winws.exe (только если есть)
            3. Запускаем BAT
            4. Ждём появления НОВОГО winws.exe
            5. Проверяем YouTube
            6. Проверяем Discord
            7. Убиваем именно созданные этим тестом winws.exe
            8. Ждём их полного завершения
            9. Закрываем cmd.exe BAT, если он всё ещё работает
            10. Возвращаем оба результата
        """
        bat_path = os.path.join(version_path, bat_name)

        if not os.path.isfile(bat_path):
            return {
                "status": "launch_error",
                "error": f"BAT файл не найден: {bat_path}",
                "youtube": None,
                "discord": None,
                "pids": []
            }

        # ========================================================
        # 1. Фиксируем старые процессы
        # ========================================================

        if progress_callback:
            progress_callback("⏳ Остановка старых процессов...")

        old_pids = set(get_winws_pids())

        if old_pids:
            kill_winws()
            wait_until_no_winws(timeout=PROCESS_STOP_TIMEOUT)

        # ========================================================
        # 2. Запускаем BAT
        # ========================================================

        if progress_callback:
            progress_callback("⏳ Запуск...")

        proc = self._launch_bat(
            bat_path,
            version_path,
            hidden=True
        )

        if proc is None:
            return {
                "status": "launch_error",
                "error": "Не удалось запустить BAT",
                "youtube": None,
                "discord": None,
                "pids": []
            }

        # ========================================================
        # 3. Ждём НОВЫЙ winws.exe
        # ========================================================

        if progress_callback:
            progress_callback("⏳ Ожидание winws...")

        new_pids = set()
        max_iterations = int(WINWS_START_TIMEOUT / WINWS_POLL_INTERVAL)

        for _ in range(max_iterations):
            if self.shutdown_event.is_set() or self.test_cancel_event.is_set():
                break

            time.sleep(WINWS_POLL_INTERVAL)

            current_pids = set(get_winws_pids())
            new_pids = current_pids - old_pids

            if new_pids:
                break

        if not new_pids:
            # BAT запустился, но winws не появился.
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass

            # На случай частично запущенного процесса
            current_pids = set(get_winws_pids())
            extra_pids = current_pids - old_pids

            for pid in extra_pids:
                kill_process_by_pid(pid)

            return {
                "status": "launch_error",
                "error": "winws.exe не появился",
                "youtube": None,
                "discord": None,
                "pids": list(new_pids)
            }

        # ========================================================
        # 4. Проверка на остановку перед YouTube
        # ========================================================

        if self.shutdown_event.is_set() or self.test_cancel_event.is_set():
            # Останавливаем уже запущенные процессы
            for pid in new_pids:
                kill_process_by_pid(pid)
            return {
                "status": "cancelled",
                "youtube": None,
                "discord": None,
                "pids": list(new_pids)
            }

        # ========================================================
        # 5. YouTube
        # ========================================================

        if progress_callback:
            progress_callback("⏳ YouTube...")

        yt_ms = check_tcp_ping(
            "www.youtube.com",
            attempts=PING_ATTEMPTS
        )

        # ========================================================
        # 6. Проверка на остановку перед Discord
        # ========================================================

        if self.shutdown_event.is_set() or self.test_cancel_event.is_set():
            # Останавливаем процессы
            for pid in new_pids:
                kill_process_by_pid(pid)
            return {
                "status": "cancelled",
                "youtube": yt_ms,
                "discord": None,
                "pids": list(new_pids)
            }

        # ========================================================
        # 7. Discord
        # ========================================================

        if progress_callback:
            progress_callback("⏳ Discord...")

        dc_ms = check_tcp_ping(
            "discord.com",
            attempts=PING_ATTEMPTS
        )

        # ========================================================
        # 8. Останавливаем процессы этого теста
        # ========================================================

        if progress_callback:
            progress_callback("⏳ Остановка...")

        for pid in new_pids:
            kill_process_by_pid(pid)

        # ========================================================
        # 9. Ждём полного завершения
        # ========================================================

        start_wait = time.time()
        while time.time() - start_wait < PROCESS_STOP_TIMEOUT:
            remaining = set(get_winws_pids()) & new_pids
            if not remaining:
                break
            time.sleep(WINWS_POLL_INTERVAL)

        # ========================================================
        # 10. Закрываем cmd.exe BAT, если он всё ещё работает
        # ========================================================

        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

        # ========================================================
        # 11. Возвращаем результат
        # ========================================================

        if yt_ms is None and dc_ms is None:
            status = "ping_error"
        elif yt_ms is None or dc_ms is None:
            status = "partial"
        else:
            status = "success"

        return {
            "status": status,
            "youtube": yt_ms,
            "discord": dc_ms,
            "pids": list(new_pids)
        }

    # ========================================================
    # ЗАПУСК BAT (низкоуровневый)
    # ========================================================

    def _launch_bat(self, bat_path, cwd, hidden=False):
        """Запускает BAT-файл, возвращает объект Popen или None при ошибке."""
        try:
            flags = HIDDEN_WINDOW_FLAG if hidden else 0
            startupinfo = None
            if hidden:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE

            return subprocess.Popen(
                ["cmd.exe", "/c", "call", bat_path],
                cwd=cwd,
                creationflags=flags,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL if hidden else None,
                stderr=subprocess.DEVNULL if hidden else None
            )
        except Exception:
            return None

    # ========================================================
    # МАССОВЫЙ ТЕСТ
    # ========================================================

    def start_test_all(self):
        if self.testing_all:
            return
        version = self.selected_version.get()
        if not version:
            messagebox.showwarning("Внимание", "Сначала выберите версию.")
            return
        bats = self.versions_data.get(version, [])
        if not bats:
            messagebox.showwarning("Внимание", "В выбранной версии нет BAT-файлов.")
            return

        # Сбрасываем события перед новым тестом
        self.test_cancel_event.clear()
        self.shutdown_event.clear()
        
        self.testing_all = True
        self.stop_requested = False
        self.btn_test_all.configure(state="disabled", text="⏳ Тестируем...")
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")  # разрешаем остановку
        self.btn_service.configure(state="disabled")
        self.status_sub.configure(text="Тестирование всех BAT...")

        # Очищаем старые результаты
        self.bat_ping_results.clear()
        self.update_bat_list()

        threading.Thread(
            target=self._test_all_worker,
            args=(version, bats),
            daemon=True
        ).start()

    def _test_all_worker(self, version, bats):
        version_path = os.path.join(self.root_dir, version)

        for idx, bat_name in enumerate(bats):
            if self.shutdown_event.is_set() or self.test_cancel_event.is_set():
                break

            # Обновляем статус в UI
            self.after(0, self.update_bat_status, bat_name, "⏳ запуск...")

            # Вызываем единый метод тестирования
            result = self.test_single_bat(
                version_path,
                bat_name,
                progress_callback=lambda status, b=bat_name: self.after(0, self.update_bat_status, b, status)
            )

            # Обновляем UI с результатом (сохранение происходит внутри update_bat_result)
            self.after(0, self.update_bat_result, bat_name, result)

            # Небольшая пауза между тестами
            time.sleep(0.3)

        # Завершаем тестирование
        self.after(0, self._finish_test_all)

    def update_bat_status(self, bat_name, status):
        """Обновляет текст кнопки BAT (отображает статус)"""
        if bat_name in self.bat_buttons:
            btn = self.bat_buttons[bat_name]
            btn.configure(text=f"📄 {bat_name}  {status}")

    def update_bat_result(self, bat_name, result):
        """Обновляет кнопку BAT финальным результатом и сохраняет данные"""
        if bat_name not in self.bat_buttons:
            return
        yt = result.get("youtube")
        dc = result.get("discord")
        # Сохраняем в словарь
        self.bat_ping_results[bat_name] = {
            "youtube": yt,
            "discord": dc
        }
        yt_str = f"{yt} ms" if yt is not None else "❌"
        dc_str = f"{dc} ms" if dc is not None else "❌"
        display_text = f"📄 {bat_name}   YouTube: {yt_str}   Discord: {dc_str}"
        self.bat_buttons[bat_name].configure(text=display_text)

    def _finish_test_all(self):
        if self.closing:
            return
        self.testing_all = False
        self.stop_requested = False
        # Очищаем события после завершения теста
        self.test_cancel_event.clear()
        self.shutdown_event.clear()
        
        self.btn_test_all.configure(state="normal", text="📊 Тест всех")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self.btn_service.configure(state="normal")

        # Поиск лучшего BAT (по сумме пингов, если оба есть)
        best = None
        best_score = None
        for name, res in self.bat_ping_results.items():
            yt = res.get("youtube")
            dc = res.get("discord")
            if yt is not None and dc is not None:
                score = yt + dc
                if best_score is None or score < best_score:
                    best_score = score
                    best = name
        if best:
            self.status_sub.configure(text=f"Тестирование завершено. Лучший обход: {best}")
        else:
            self.status_sub.configure(text="Тестирование завершено. Нет BAT с полными данными пинга.")

        # Обновляем список, чтобы отобразить результаты
        self.update_bat_list()
        self.refresh_tray()

    # ========================================================
    # ПУТИ
    # ========================================================

    def get_current_paths(self):
        version = self.selected_version.get()
        if not version:
            return None, None
        version_path = os.path.join(self.root_dir, version)
        if not os.path.isdir(version_path):
            return None, None

        service_path = None
        exact_service = os.path.join(version_path, "service.bat")
        if os.path.isfile(exact_service):
            service_path = exact_service
        else:
            try:
                for filename in os.listdir(version_path):
                    if filename.lower().startswith("service") and filename.lower().endswith(".bat"):
                        service_path = os.path.join(version_path, filename)
                        break
            except Exception:
                pass

        return version_path, service_path

    # ========================================================
    # УПРАВЛЕНИЕ СЕРВИСОМ (окно)
    # ========================================================

    def open_service_manager(self):
        """Открывает окно управления сервисом."""
        if self.testing_all:
            return
        
        # Проверяем права администратора
        if not ServiceManager.is_admin():
            messagebox.showerror(
                "Ошибка",
                "Для управления сервисом требуются права администратора.\n\n"
                "Перезапустите приложение от имени администратора."
            )
            return
        
        service_window = ServiceManagerWindow(self)
        service_window.grab_set()


    # ========================================================
    # ЗАПУСК ZAPRET (ОБЫЧНЫЙ)
    # ========================================================

    def start_process(self):
        if self.protection_starting or self.testing_all:
            return

        version_path, _ = self.get_current_paths()
        bat_name = self.selected_bat.get()

        if not version_path:
            messagebox.showwarning("Внимание", "Выберите версию Zapret.")
            return
        if not bat_name:
            messagebox.showwarning("Внимание", "Выберите BAT-файл обхода.")
            return

        bat_path = os.path.join(version_path, bat_name)
        if not os.path.isfile(bat_path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n\n{bat_path}")
            return

        self.protection_starting = True
        self.btn_start.configure(state="disabled", text="Запуск...")

        threading.Thread(
            target=self._start_process_worker,
            args=(version_path, bat_path),
            daemon=True
        ).start()

    def _start_process_worker(self, version_path, bat_path):
        try:
            # Фиксируем старые PID
            old_pids = set(get_winws_pids())

            # Убиваем старые процессы и ждём их завершения
            if old_pids:
                kill_winws()
                wait_until_no_winws(timeout=PROCESS_STOP_TIMEOUT)

            # Запускаем BAT с учётом настройки hidden
            proc = self._launch_bat(bat_path, version_path, hidden=self.run_bat_hidden)
            if proc is None:
                self.after(0, self._start_error, "Не удалось запустить BAT")
                return

            # Ждём появления НОВОГО winws.exe
            managed_pids = set()
            max_iterations = int(WINWS_START_TIMEOUT / WINWS_POLL_INTERVAL)
            
            for _ in range(max_iterations):
                time.sleep(WINWS_POLL_INTERVAL)
                current_pids = set(get_winws_pids())
                new_pids = current_pids - old_pids
                if new_pids:
                    managed_pids.update(new_pids)
                    break

            if not managed_pids:
                self.after(0, self._start_error, "winws.exe не появился")
                return

            # Сохраняем все найденные PID управляемых процессов
            self.managed_pids = managed_pids
            if not self.closing:
                self.after(0, self._finish_start, True)

        except Exception as error:
            if not self.closing:
                self.after(0, self._start_error, str(error))

    def _finish_start(self, running):
        if self.closing:
            return
        self.protection_starting = False
        self.btn_start.configure(state="normal", text="Запуск")

        version = self.selected_version.get()
        bat = self.selected_bat.get()

        if running:
            self.status_title.configure(text="● ЗАЩИТА АКТИВНА", text_color="#10B981")
            self.status_sub.configure(text=f"Версия: {version} | Обход: {bat}")
            self.run_ping_check()
        else:
            self.status_title.configure(text="● ОШИБКА ЗАПУСКА", text_color="#EF4444")
            self.status_sub.configure(text="winws.exe не обнаружен. Проверьте выбранный BAT.")

        self.refresh_tray()

    def _start_error(self, error):
        if self.closing:
            return
        self.protection_starting = False
        self.btn_start.configure(state="normal", text="Запуск")
        self.status_title.configure(text="● ОШИБКА", text_color="#EF4444")
        self.status_sub.configure(text="Ошибка запуска Zapret")
        messagebox.showerror("Ошибка запуска", error)

    # ========================================================
    # ОСТАНОВКА (обычная и прерывание теста)
    # ========================================================

    def stop_process(self):
        if self.stopping:
            return
        # Если идёт массовый тест, просто устанавливаем флаг остановки
        if self.testing_all:
            self.test_cancel_event.set()
            self.btn_stop.configure(state="disabled", text="Остановка...")
            return

        # Иначе останавливаем обычный режим
        self.stopping = True
        self.btn_stop.configure(state="disabled", text="Остановка...")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self):
        # Очищаем все управляемые процессы
        for pid in self.managed_pids:
            kill_process_by_pid(pid)
        self.managed_pids.clear()
        
        # Дополнительно убиваем любые оставшиеся winws.exe на всякий случай
        kill_winws()
        
        self.after(0, self._update_stop_ui)

    def _update_stop_ui(self):
        if self.closing:
            return
        self.stopping = False
        self.btn_stop.configure(state="normal", text="Стоп")
        self.status_title.configure(text="● ОСТАНОВЛЕНО", text_color="#EF4444")
        self.status_sub.configure(text="Выберите версию и обход")
        self.refresh_tray()

    # ========================================================
    # PING (для активного режима)
    # ========================================================

    def run_ping_check(self):
        if self.testing_all:
            return
        self.btn_check_ping.configure(state="disabled", text="⏳...")
        threading.Thread(target=self._ping_worker, daemon=True).start()

    def _ping_worker(self):
        yt_ms = check_tcp_ping("www.youtube.com")
        dc_ms = check_tcp_ping("discord.com")
        if not self.closing:
            self.after(0, self._update_ping_ui, yt_ms, dc_ms)

    def _update_ping_ui(self, yt_ms, dc_ms):
        if self.closing:
            return
        if yt_ms is None or yt_ms > 2000:
            self.yt_ping_label.configure(text="YouTube: ❌ Ошибка", text_color="#EF4444")
        else:
            text_color = "#10B981" if yt_ms < 100 else ("#F59E0B" if yt_ms < 200 else "#EF4444")
            self.yt_ping_label.configure(text=f"YouTube: {yt_ms} ms", text_color=text_color)

        if dc_ms is None or dc_ms > 2000:
            self.dc_ping_label.configure(text="Discord: ❌ Ошибка", text_color="#EF4444")
        else:
            text_color = "#10B981" if dc_ms < 100 else ("#F59E0B" if dc_ms < 200 else "#EF4444")
            self.dc_ping_label.configure(text=f"Discord: {dc_ms} ms", text_color=text_color)

        self.btn_check_ping.configure(state="normal", text="⚡ Проверить")

    # ========================================================
    # НАСТРОЙКИ (меню)
    # ========================================================

    def show_settings_menu(self):
        menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1E2029",
            fg="#FFFFFF",
            activebackground="#10B981",
            activeforeground="#FFFFFF"
        )
        menu.add_command(label="📁 Сменить корневую папку", command=self.change_root_folder)
        menu.add_command(label="📂 Открыть текущую папку", command=self.open_current_folder)
        menu.add_separator()
        # Пункт для фонового запуска
        hidden_status = "☑" if self.run_bat_hidden else "☐"
        menu.add_command(label=f"{hidden_status} Запускать BAT в фоне", command=self.toggle_hidden_mode)
        menu.add_separator()
        menu.add_command(label="🔄 Обновить список версий", command=self.refresh_versions)
        menu.add_separator()
        menu.add_command(label="❌ Выход", command=self.quit_app)

        x = self.settings_btn.winfo_rootx()
        y = self.settings_btn.winfo_rooty() + self.settings_btn.winfo_height() + 4
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def toggle_hidden_mode(self):
        """Переключает режим фонового запуска BAT."""
        self.run_bat_hidden = not self.run_bat_hidden
        save_config(self.root_dir, self.run_bat_hidden)

    def change_root_folder(self):
        if self.testing_all:
            return
        folder = filedialog.askdirectory(
            initialdir=self.root_dir if os.path.isdir(self.root_dir) else os.path.expanduser("~"),
            title="Выберите папку ALL_VERSIONS"
        )
        if not folder:
            return
        self.root_dir = folder
        save_config(self.root_dir, self.run_bat_hidden)
        self.selected_version.set("")
        self.selected_bat.set("")
        self.bat_ping_results.clear()
        self.render_versions_list()
        self.update_window_icon()
        self.status_sub.configure(text="Папка обновлена. Выберите версию.")

    def refresh_versions(self):
        if self.testing_all:
            return
        self.selected_version.set("")
        self.selected_bat.set("")
        self.bat_ping_results.clear()
        self.render_versions_list()
        self.update_window_icon()
        self.status_sub.configure(text="Список версий обновлён")

    def open_current_folder(self):
        version_path, _ = self.get_current_paths()
        if version_path and os.path.isdir(version_path):
            os.startfile(version_path)
            return
        if os.path.isdir(self.root_dir):
            os.startfile(self.root_dir)

    # ========================================================
    # ТРЕЙ (pystray)
    # ========================================================

    def setup_tray(self):
        if self.tray_icon is not None:
            return
        image = self.icon_image if self.icon_image else self.create_default_icon()
        self.tray_icon = pystray.Icon(
            "ZapretManager",
            image,
            "Zapret Manager",
            menu=self._build_tray_menu()
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _build_tray_menu(self):
        # Строим меню трея
        version_items = []
        for version_name in self.versions_data.keys():
            # Создаём замыкание для действия
            def make_action(v):
                return lambda icon, item: self.after(0, self.select_version, v)
            # Создаём замыкание для checked
            def make_checked(v):
                return lambda icon, item: self.selected_version.get() == v
            version_items.append(
                item(
                    version_name,
                    make_action(version_name),
                    checked=make_checked(version_name)
                )
            )
        if not version_items:
            version_items.append(item("Нет версий", lambda icon, menu_item: None, enabled=False))

        version_menu = pystray.Menu(*version_items)

        menu = pystray.Menu(
            item("Открыть окно", lambda icon, menu_item: self.after(0, self.show_from_tray), default=True),
            item("Запуск", lambda icon, menu_item: self.after(0, self.start_process)),
            item("Стоп", lambda icon, menu_item: self.after(0, self.stop_process)),
            item("Сменить версию", version_menu),
            pystray.Menu.SEPARATOR,
            item("Управление сервисом", lambda icon, menu_item: self.after(0, self.open_service_manager)),
            pystray.Menu.SEPARATOR,
            item("Выход", lambda icon, menu_item: self.after(0, self.quit_app))
        )
        return menu

    def refresh_tray(self):
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.menu = self._build_tray_menu()
            if self.icon_image:
                self.tray_icon.icon = self.icon_image
            self.tray_icon.update_menu()
        except Exception as error:
            print(f"Ошибка обновления трея: {error}")

    def hide_to_tray(self):
        self.withdraw()

    def show_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    # ========================================================
    # ЗАКРЫТИЕ
    # ========================================================

    def quit_app(self):
        if self.closing:
            return
        self.closing = True

        # Сигнализируем о полном завершении приложения
        self.shutdown_event.set()
        
        # Отменяем текущий тест, если он идёт
        self.test_cancel_event.set()

        # Останавливаем все процессы
        kill_winws()
        self.managed_pids.clear()

        # Останавливаем тестирование
        self.testing_all = False
        self.stop_requested = True

        # Закрываем трей
        try:
            if self.tray_icon:
                self.tray_icon.visible = False
                self.tray_icon.stop()
                self.tray_icon = None
        except Exception:
            pass

        # Небольшая задержка для корректного закрытия трея
        time.sleep(0.1)

        # Закрываем окно
        try:
            self.destroy()
        except Exception:
            pass

        release_mutex()
        sys.exit()


# ============================================================
# ОКНО УПРАВЛЕНИЯ СЕРВИСОМ
# ============================================================

class ServiceManagerWindow(ctk.CTkToplevel):
    """Окно управления сервисом Zapret."""

    def __init__(self, parent):
        super().__init__(parent)
        
        self.title("Управление сервисом Zapret")
        self.geometry("500x480")
        self.resizable(False, False)
        self.configure(fg_color="#121318")
        
        self.parent = parent
        self.service_exists = False
        self.service_running = False
        self.current_strategy = None
        
        self.create_interface()
        self.refresh_status()
        
        # Периодическое обновление статуса
        self.update_status_periodically()

    def create_interface(self):
        """Создаёт интерфейс окна."""
        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Управление сервисом Windows",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#FFFFFF"
        )
        header.pack(pady=(16, 8))

        # Карточка статуса
        status_card = ctk.CTkFrame(
            self,
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            corner_radius=10
        )
        status_card.pack(fill="x", padx=16, pady=8)

        self.status_label = ctk.CTkLabel(
            status_card,
            text="Статус: Проверка...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#F59E0B"
        )
        self.status_label.pack(pady=10)

        self.strategy_label = ctk.CTkLabel(
            status_card,
            text="Стратегия: --",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF"
        )
        self.strategy_label.pack(pady=(0, 10))

        # Кнопки управления
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=8)

        self.btn_install = ctk.CTkButton(
            btn_frame,
            text="📥 Установить сервис",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#3B82F6",
            hover_color="#2563EB",
            height=36,
            command=self.install_service
        )
        self.btn_install.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.btn_delete = ctk.CTkButton(
            btn_frame,
            text="🗑 Удалить сервис",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#EF4444",
            hover_color="#DC2626",
            height=36,
            command=self.delete_service
        )
        self.btn_delete.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Кнопки запуска/остановки
        run_frame = ctk.CTkFrame(self, fg_color="transparent")
        run_frame.pack(fill="x", padx=16, pady=8)

        self.btn_start = ctk.CTkButton(
            run_frame,
            text="▶ Запустить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10B981",
            hover_color="#059669",
            height=36,
            command=self.start_service
        )
        self.btn_start.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.btn_stop = ctk.CTkButton(
            run_frame,
            text="⏹ Остановить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#F59E0B",
            hover_color="#D97706",
            height=36,
            command=self.stop_service
        )
        self.btn_stop.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Кнопка перезапуска
        self.btn_restart = ctk.CTkButton(
            self,
            text="🔄 Перезапустить",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#8B5CF6",
            hover_color="#7C3AED",
            height=36,
            command=self.restart_service
        )
        self.btn_restart.pack(fill="x", padx=16, pady=8)

        # Разделитель
        separator = ctk.CTkFrame(self, fg_color="#2E3240", height=2)
        separator.pack(fill="x", padx=16, pady=12)

        # Информация о winws.exe
        info_label = ctk.CTkLabel(
            self,
            text="Информация о процессе:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFFFFF"
        )
        info_label.pack(anchor="w", padx=16)

        self.winws_status_label = ctk.CTkLabel(
            self,
            text="winws.exe: Проверка...",
            font=ctk.CTkFont(size=11),
            text_color="#9CA3AF"
        )
        self.winws_status_label.pack(anchor="w", padx=16, pady=(4, 8))

        # Кнопка закрытия
        close_btn = ctk.CTkButton(
            self,
            text="Закрыть",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            hover_color="#2E3240",
            height=36,
            command=self.destroy
        )
        close_btn.pack(fill="x", padx=16, pady=(0, 16))

    def refresh_status(self):
        """Обновляет статус сервиса."""
        try:
            self.service_exists = ServiceManager.check_service_exists()
            
            if self.service_exists:
                status = ServiceManager.get_service_status()
                self.current_strategy = ServiceManager.get_service_strategy()
                
                if status == "RUNNING":
                    self.service_running = True
                    self.status_label.configure(
                        text="● Сервис ЗАПУЩЕН",
                        text_color="#10B981"
                    )
                elif status == "STOPPED":
                    self.service_running = False
                    self.status_label.configure(
                        text="● Сервис ОСТАНОВЛЕН",
                        text_color="#F59E0B"
                    )
                elif status == "STOP_PENDING":
                    self.status_label.configure(
                        text="⏳ Остановка...",
                        text_color="#F59E0B"
                    )
                elif status == "START_PENDING":
                    self.status_label.configure(
                        text="⏳ Запуск...",
                        text_color="#10B981"
                    )
                else:
                    self.status_label.configure(
                        text=f"● Статус: {status}",
                        text_color="#9CA3AF"
                    )
                
                if self.current_strategy:
                    self.strategy_label.configure(text=f"Стратегия: {self.current_strategy}")
                else:
                    self.strategy_label.configure(text="Стратегия: не установлена")
            else:
                self.service_running = False
                self.current_strategy = None
                self.status_label.configure(
                    text="○ Сервис НЕ установлен",
                    text_color="#EF4444"
                )
                self.strategy_label.configure(text="Стратегия: --")
            
            # Обновляем состояние кнопок
            self.btn_install.configure(state="normal" if not self.service_exists else "disabled")
            self.btn_delete.configure(state="normal" if self.service_exists else "disabled")
            self.btn_start.configure(state="normal" if (self.service_exists and not self.service_running) else "disabled")
            self.btn_stop.configure(state="normal" if self.service_running else "disabled")
            self.btn_restart.configure(state="normal" if self.service_running else "disabled")
            
            # Проверяем winws.exe
            if ServiceManager.is_winws_running():
                self.winws_status_label.configure(
                    text="winws.exe: РАБОТАЕТ",
                    text_color="#10B981"
                )
            else:
                self.winws_status_label.configure(
                    text="winws.exe: НЕ запущен",
                    text_color="#9CA3AF"
                )
        except Exception as e:
            self.status_label.configure(text=f"Ошибка: {str(e)}", text_color="#EF4444")

    def update_status_periodically(self):
        """Периодически обновляет статус."""
        if self.winfo_exists():
            self.refresh_status()
            self.after(2000, self.update_status_periodically)

    def install_service(self):
        """Устанавливает сервис."""
        version_path, _ = self.parent.get_current_paths()
        bat_name = self.parent.selected_bat.get()
        
        if not version_path:
            messagebox.showwarning("Внимание", "Выберите версию Zapret в главном окне.")
            return
        if not bat_name:
            messagebox.showwarning("Внимание", "Выберите BAT-файл обхода в главном окне.")
            return
        
        bat_path = os.path.join(version_path, bat_name)
        bin_path = os.path.join(version_path, "bin", "winws.exe")
        
        if not os.path.isfile(bat_path):
            messagebox.showerror("Ошибка", f"BAT файл не найден:\n{bat_path}")
            return
        if not os.path.isfile(bin_path):
            messagebox.showerror("Ошибка", f"winws.exe не найден:\n{bin_path}")
            return
        
        # Читаем аргументы из BAT файла
        args = self.parse_bat_args(bat_path)
        if not args:
            messagebox.showerror("Ошибка", "Не удалось прочитать аргументы из BAT файла.")
            return
        
        # Подтверждение
        result = messagebox.askyesno(
            "Подтверждение",
            f"Установить сервис Zapret?\n\n"
            f"Путь: {bin_path}\n"
            f"Аргументы: {args[:100]}{'...' if len(args) > 100 else ''}\n\n"
            f"Будет создан системный сервис 'zapret', который запускается автоматически."
        )
        if not result:
            return
        
        # Выполняем установку
        self.btn_install.configure(state="disabled", text="⏳ Установка...")
        
        def do_install():
            success, message = ServiceManager.install_service(bin_path, args)
            self.after(0, self._install_complete, success, message)
        
        threading.Thread(target=do_install, daemon=True).start()

    def parse_bat_args(self, bat_path):
        """Извлекает аргументы командной строки из BAT файла."""
        try:
            with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            # Ищем строку с winws.exe
            for line in content.splitlines():
                if "winws.exe" in line.lower():
                    # Извлекаем всё после winws.exe
                    idx = line.lower().find("winws.exe")
                    if idx >= 0:
                        args_part = line[idx + 9:].strip()
                        # Удаляем комментарии и лишнее
                        if "::" in args_part:
                            args_part = args_part.split("::")[0].strip()
                        if "rem " in args_part.lower():
                            args_part = args_part.split("rem ")[0].strip()
                        return args_part
            return None
        except Exception:
            return None

    def _install_complete(self, success, message):
        """Обработка завершения установки."""
        self.btn_install.configure(state="normal", text="📥 Установить сервис")
        if success:
            messagebox.showinfo("Успех", message)
            self.refresh_status()
        else:
            messagebox.showerror("Ошибка", message)

    def delete_service(self):
        """Удаляет сервис."""
        result = messagebox.askyesno(
            "Подтверждение",
            "Удалить сервис Zapret?\n\n"
            "Это удалит сервис из системы.\n"
            "winws.exe будет остановлен."
        )
        if not result:
            return
        
        self.btn_delete.configure(state="disabled", text="⏳ Удаление...")
        
        def do_delete():
            success, message = ServiceManager.delete_service()
            self.after(0, self._delete_complete, success, message)
        
        threading.Thread(target=do_delete, daemon=True).start()

    def _delete_complete(self, success, message):
        """Обработка завершения удаления."""
        self.btn_delete.configure(state="normal", text="🗑 Удалить сервис")
        if success:
            messagebox.showinfo("Успех", message)
            self.refresh_status()
        else:
            messagebox.showerror("Ошибка", message)

    def start_service(self):
        """Запускает сервис."""
        self.btn_start.configure(state="disabled", text="⏳ Запуск...")
        
        def do_start():
            success, message = ServiceManager.start_service()
            self.after(0, self._start_complete, success, message)
        
        threading.Thread(target=do_start, daemon=True).start()

    def _start_complete(self, success, message):
        """Обработка завершения запуска."""
        self.btn_start.configure(state="normal", text="▶ Запустить")
        if success:
            self.refresh_status()
        else:
            messagebox.showerror("Ошибка", message)

    def stop_service(self):
        """Останавливает сервис."""
        self.btn_stop.configure(state="disabled", text="⏳ Остановка...")
        
        def do_stop():
            success, message = ServiceManager.stop_service()
            self.after(0, self._stop_complete, success, message)
        
        threading.Thread(target=do_stop, daemon=True).start()

    def _stop_complete(self, success, message):
        """Обработка завершения остановки."""
        self.btn_stop.configure(state="normal", text="⏹ Остановить")
        if success:
            self.refresh_status()
        else:
            messagebox.showerror("Ошибка", message)

    def restart_service(self):
        """Перезапускает сервис."""
        self.btn_restart.configure(state="disabled", text="⏳ Перезапуск...")
        
        def do_restart():
            success, message = ServiceManager.restart_service()
            self.after(0, self._restart_complete, success, message)
        
        threading.Thread(target=do_restart, daemon=True).start()

    def _restart_complete(self, success, message):
        """Обработка завершения перезапуска."""
        self.btn_restart.configure(state="normal", text="🔄 Перезапустить")
        if success:
            self.refresh_status()
        else:
            messagebox.showerror("Ошибка", message)


# ============================================================
# ЗАПУСК ОТ АДМИНИСТРАТОРА С ПРОВЕРКОЙ ЕДИНСТВЕННОГО ЭКЗЕМПЛЯРА
# ============================================================

if __name__ == "__main__":

    if not is_admin():
        try:
            if getattr(sys, "frozen", False):
                executable = sys.executable
                params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
            else:
                executable = sys.executable
                params = " ".join([f'"{sys.argv[0]}"'] + [f'"{arg}"' for arg in sys.argv[1:]])

            ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)

        except Exception as error:
            messagebox.showerror("Ошибка", f"Не удалось получить права администратора:\n\n{error}")

        sys.exit()

    created, handle = create_mutex()
    if not created:
        activate_existing_window()
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
        sys.exit()

    app = ZapretLauncher()

    if not os.path.isdir(app.root_dir):
        app.after(100, app.ask_for_folder)

    try:
        app.mainloop()
    finally:
        release_mutex()
