"""
ZapretManager - GUI Application Module
"""

import threading
import os
import json
import time
import queue
import urllib.error
import urllib.request
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import customtkinter as ctk

from .config import (
    APP_NAME,
    DEFAULT_ROOT_DIR,
    LOCAL_VERSION,
    GITHUB_VERSION_URL,
    GITHUB_DOWNLOAD_URL,
    GITHUB_IPSET_URL,
    GITHUB_HOSTS_URL,
    WINWS_START_TIMEOUT,
    WINWS_POLL_INTERVAL,
    PING_ATTEMPTS,
    PING_INTERVAL,
    PING_TIMEOUT,
    SERVICE_POLL_INTERVAL,
    SERVICE_START_TIMEOUT,
    SERVICE_STOP_TIMEOUT,
)
from .utils import (
    load_config,
    save_config,
    is_admin,
    launch_as_admin,
    check_tcp_ping,
    get_winws_pids,
    is_winws_running,
    kill_process_by_pid,
    kill_winws,
    wait_until_no_winws,
    create_mutex,
    release_mutex,
    activate_existing_window,
    normalize_bat_name,
)
from .bat_parser import (
    parse_bat_winws_args,
    get_bat_files,
)
from .service_manager import ServiceManager


class ZapretLauncher(ctk.CTk):

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")

        self.config_data = load_config()

        self.root_dir = self.config_data.get(
            "root_dir",
            DEFAULT_ROOT_DIR,
        )

        self.selected_version = ctk.StringVar(
            value=""
        )

        self.selected_bat = ctk.StringVar(
            value=""
        )

        self.version_buttons = {}
        self.bat_cards = {}
        self.versions_data = {}
        self.bat_ping_results = {}

        self.tray_icon = None
        self.icon_image = None
        self.temp_icon_path = None

        self.tray_stop_lock = threading.Lock()

        # ----------------------------------------------------
        # Состояние приложения
        # ----------------------------------------------------

        self.protection_starting = False
        self.testing_all = False
        self.stop_requested = False
        self.stopping = False
        self.closing = False

        self.managed_pids = set()

        self.shutdown_event = threading.Event()
        self.test_cancel_event = threading.Event()

        self.testing_thread = None

        self.service_operation_in_progress = False

        # ----------------------------------------------------
        # НОВОЕ: защита от повторных фоновых обновлений
        # ----------------------------------------------------

        self.service_refresh_after_id = None
        self.service_refresh_running = False
        self.service_refresh_pending = False

        # Версия запроса нужна, чтобы старый поток не перезаписал
        # более свежие данные.
        self.service_refresh_generation = 0

        # ----------------------------------------------------
        # НОВОЕ: debounce для Tray
        # ----------------------------------------------------

        self.tray_refresh_after_id = None

        self.title(APP_NAME)
        self.geometry("780x900")
        self.minsize(740, 820)
        self.resizable(True, True)
        self.configure(
            fg_color="#121318"
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self.hide_to_tray,
        )

        self.create_interface()

        # Иконка загружается один раз при старте.
        self.update_window_icon(
            refresh_tray=False
        )

        self.render_versions_list()

        self.setup_tray()

        self.start_service_status_polling()

    # ========================================================
    # INTERFACE
    # ========================================================

    def create_interface(self):

        self.main_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color="#2E3240",
            scrollbar_button_hover_color="#374151",
        )

        self.main_scroll.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=0,
        )

        # HEADER
        self.header_frame = ctk.CTkFrame(
            self.main_scroll,
            fg_color="transparent",
            height=38,
        )

        self.header_frame.pack(
            fill="x",
            padx=8,
            pady=(14, 10),
        )

        self.logo_label = ctk.CTkLabel(
            self.header_frame,
            text=" Zapret Multi-Manager",
            font=ctk.CTkFont(
                size=18,
                weight="bold",
            ),
            text_color="#FFFFFF",
        )

        self.logo_label.pack(
            side="left"
        )

        self.settings_btn = ctk.CTkButton(
            self.header_frame,
            text="⚙",
            width=34,
            height=30,
            fg_color="transparent",
            hover_color="#1E2029",
            text_color="#9CA3AF",
            font=ctk.CTkFont(size=18),
            command=self.show_settings_menu,
        )

        self.settings_btn.pack(
            side="right"
        )

        # STATUS
        self.status_card = self.make_card(
            self.main_scroll
        )

        self.status_card.pack(
            fill="x",
            padx=8,
            pady=(0, 10),
        )

        self.status_title = ctk.CTkLabel(
            self.status_card,
            text="● ОСТАНОВЛЕНО",
            font=ctk.CTkFont(
                size=14,
                weight="bold",
            ),
            text_color="#EF4444",
        )

        self.status_title.pack(
            anchor="w",
            padx=14,
            pady=(10, 2),
        )

        self.status_sub = ctk.CTkLabel(
            self.status_card,
            text="Выберите версию и обход",
            font=ctk.CTkFont(size=11),
            text_color="#9CA3AF",
            wraplength=720,
            justify="left",
        )

        self.status_sub.pack(
            anchor="w",
            padx=14,
            pady=(0, 10),
        )

        # PING
        self.ping_card = self.make_card(
            self.main_scroll
        )

        self.ping_card.pack(
            fill="x",
            padx=8,
            pady=(0, 10),
        )

        ping_title_frame = ctk.CTkFrame(
            self.ping_card,
            fg_color="transparent",
        )

        ping_title_frame.pack(
            fill="x",
            padx=14,
            pady=(8, 4),
        )

        ctk.CTkLabel(
            ping_title_frame,
            text="ПИНГ СЕРВЕРОВ",
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            side="left"
        )

        self.btn_check_ping = ctk.CTkButton(
            ping_title_frame,
            text="⚡ Проверить",
            width=90,
            height=24,
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            fg_color="#2E3240",
            hover_color="#374151",
            text_color="#FFFFFF",
            corner_radius=6,
            command=self.run_ping_check,
        )

        self.btn_check_ping.pack(
            side="right"
        )

        ping_labels = ctk.CTkFrame(
            self.ping_card,
            fg_color="transparent",
        )

        ping_labels.pack(
            fill="x",
            padx=14,
            pady=(0, 9),
        )

        self.yt_ping_label = ctk.CTkLabel(
            ping_labels,
            text="YouTube: -- ms",
            font=ctk.CTkFont(
                size=12,
                weight="bold",
            ),
            text_color="#9CA3AF",
        )

        self.yt_ping_label.pack(
            side="left",
            fill="x",
            expand=True,
            anchor="w",
        )

        self.dc_ping_label = ctk.CTkLabel(
            ping_labels,
            text="Discord: -- ms",
            font=ctk.CTkFont(
                size=12,
                weight="bold",
            ),
            text_color="#9CA3AF",
        )

        self.dc_ping_label.pack(
            side="left",
            fill="x",
            expand=True,
            anchor="e",
        )

        # ====================================================
        # VERSIONS + BAT
        # ====================================================

        main_card = self.make_card(
            self.main_scroll
        )

        main_card.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=(0, 10),
        )

        columns = ctk.CTkFrame(
            main_card,
            fg_color="transparent",
        )

        columns.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        left_col = ctk.CTkFrame(
            columns,
            fg_color="transparent",
            width=250,
        )

        left_col.pack(
            side="left",
            fill="both",
            expand=False,
            padx=(0, 6),
        )

        right_col = ctk.CTkFrame(
            columns,
            fg_color="transparent",
        )

        right_col.pack(
            side="left",
            fill="both",
            expand=True,
            padx=(6, 0),
        )

        ctk.CTkLabel(
            left_col,
            text="ВЕРСИЯ ZAPRET",
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            pady=(0, 4),
        )

        self.version_scroll_frame = ctk.CTkScrollableFrame(
            left_col,
            fg_color="transparent",
            height=250,
            scrollbar_button_color="#2E3240",
            scrollbar_button_hover_color="#374151",
        )

        self.version_scroll_frame.pack(
            fill="both",
            expand=True,
        )

        bat_header = ctk.CTkFrame(
            right_col,
            fg_color="transparent",
        )

        bat_header.pack(
            fill="x",
            pady=(0, 4),
        )

        ctk.CTkLabel(
            bat_header,
            text="ОБХОД (.BAT)",
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            side="left"
        )

        self.btn_test_all = ctk.CTkButton(
            bat_header,
            text="📊 Тест всех",
            width=100,
            height=24,
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            fg_color="#2E3240",
            hover_color="#374151",
            text_color="#FFFFFF",
            corner_radius=6,
            command=self.start_test_all,
        )

        self.btn_test_all.pack(
            side="right"
        )

        self.scroll_frame = ctk.CTkScrollableFrame(
            right_col,
            fg_color="transparent",
            height=360,
            scrollbar_button_color="#2E3240",
            scrollbar_button_hover_color="#374151",
        )

        self.scroll_frame.pack(
            fill="both",
            expand=True,
        )

        # ====================================================
        # SERVICE CARD
        # ====================================================

        self.service_card = self.make_card(
            self.main_scroll
        )

        self.service_card.pack(
            fill="x",
            padx=8,
            pady=(0, 10),
        )

        self.create_service_interface()

        # ====================================================
        # MAIN ACTIONS
        # ====================================================

        self.buttons_container = ctk.CTkFrame(
            self.main_scroll,
            fg_color="transparent",
        )

        self.buttons_container.pack(
            fill="x",
            padx=8,
            pady=(0, 16),
        )

        self.btn_start = ctk.CTkButton(
            self.buttons_container,
            text="▶ Запустить BAT",
            font=ctk.CTkFont(
                size=14,
                weight="bold",
            ),
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#FFFFFF",
            height=42,
            corner_radius=8,
            command=self.start_process,
        )

        self.btn_start.pack(
            fill="x",
            pady=(0, 8),
        )

        self.btn_stop = ctk.CTkButton(
            self.buttons_container,
            text="⏹ Остановить BAT",
            font=ctk.CTkFont(
                size=13,
                weight="bold",
            ),
            fg_color="#1A1B23",
            border_color="#EF4444",
            border_width=1,
            hover_color="#2A1215",
            text_color="#EF4444",
            height=38,
            corner_radius=8,
            command=self.stop_process,
        )

        self.btn_stop.pack(
            fill="x",
            pady=(0, 8),
        )

        self.btn_quit = ctk.CTkButton(
            self.buttons_container,
            text="❌ Выйти полностью",
            font=ctk.CTkFont(
                size=13,
                weight="bold",
            ),
            fg_color="#1A1B23",
            border_color="#EF4444",
            border_width=1,
            hover_color="#2A1215",
            text_color="#EF4444",
            height=36,
            corner_radius=8,
            command=self.quit_app,
        )

        self.btn_quit.pack(
            fill="x"
        )

    @staticmethod
    def make_card(parent):
        return ctk.CTkFrame(
            parent,
            fg_color="#1E2029",
            border_color="#2E3240",
            border_width=1,
            corner_radius=10,
        )

    # ========================================================
    # SERVICE UI
    # ========================================================

    def create_service_interface(self):

        ctk.CTkLabel(
            self.service_card,
            text="СЕРВИС WINDOWS",
            font=ctk.CTkFont(
                size=12,
                weight="bold",
            ),
            text_color="#FFFFFF",
        ).pack(
            anchor="w",
            padx=14,
            pady=(11, 4),
        )

        self.service_status_label = ctk.CTkLabel(
            self.service_card,
            text="○ Сервис НЕ установлен",
            font=ctk.CTkFont(
                size=13,
                weight="bold",
            ),
            text_color="#EF4444",
        )

        self.service_status_label.pack(
            anchor="w",
            padx=14,
            pady=(0, 2),
        )

        self.service_strategy_label = ctk.CTkLabel(
            self.service_card,
            text="Стратегия: --",
            font=ctk.CTkFont(size=11),
            text_color="#9CA3AF",
            wraplength=720,
            justify="left",
        )

        self.service_strategy_label.pack(
            anchor="w",
            padx=14,
            pady=2,
        )

        self.service_process_label = ctk.CTkLabel(
            self.service_card,
            text="winws.exe: --",
            font=ctk.CTkFont(size=11),
            text_color="#9CA3AF",
        )

        self.service_process_label.pack(
            anchor="w",
            padx=14,
            pady=(0, 8),
        )

        row1 = ctk.CTkFrame(
            self.service_card,
            fg_color="transparent",
        )

        row1.pack(
            fill="x",
            padx=14,
            pady=4,
        )

        self.btn_service_install = self.service_button(
            row1,
            "📥 Установить сервис",
            "#3B82F6",
            self.install_service,
        )

        self.btn_service_install.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 4),
        )

        self.btn_service_delete = self.service_button(
            row1,
            "🗑 Удалить сервис",
            "#EF4444",
            self.delete_service,
        )

        self.btn_service_delete.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 0),
        )

        row2 = ctk.CTkFrame(
            self.service_card,
            fg_color="transparent",
        )

        row2.pack(
            fill="x",
            padx=14,
            pady=4,
        )

        self.btn_service_start = self.service_button(
            row2,
            "▶ Запустить сервис",
            "#10B981",
            self.start_service,
        )

        self.btn_service_start.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 4),
        )

        self.btn_service_stop = self.service_button(
            row2,
            "⏹ Остановить сервис",
            "#F59E0B",
            self.stop_service,
        )

        self.btn_service_stop.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 0),
        )

        row3 = ctk.CTkFrame(
            self.service_card,
            fg_color="transparent",
        )

        row3.pack(
            fill="x",
            padx=14,
            pady=(4, 8),
        )

        self.btn_service_restart = self.service_button(
            row3,
            "🔄 Перезапустить сервис",
            "#8B5CF6",
            self.restart_service,
        )

        self.btn_service_restart.pack(
            fill="x"
        )

        sections = ctk.CTkFrame(
            self.service_card,
            fg_color="transparent",
        )

        sections.pack(
            fill="x",
            padx=14,
            pady=(0, 10),
        )

        # SETTINGS
        ctk.CTkLabel(
            sections,
            text="НАСТРОЙКИ",
            font=ctk.CTkFont(
                size=10,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            pady=(4, 5),
        )

        settings_row = ctk.CTkFrame(
            sections,
            fg_color="transparent",
        )

        settings_row.pack(
            fill="x"
        )

        self.game_filter_var = tk.StringVar(
            value="disabled"
        )

        self.ipset_mode_var = tk.StringVar(
            value="any"
        )

        self.auto_update_var = tk.StringVar(
            value="disabled"
        )

        def make_setting_column(
            title,
            description,
            option,
        ):
            column = ctk.CTkFrame(
                settings_row,
                fg_color="#15161D",
                corner_radius=7,
                border_width=1,
                border_color="#2E3240",
            )

            column.pack(
                side="left",
                fill="both",
                expand=True,
                padx=3,
            )

            ctk.CTkLabel(
                column,
                text=title,
                anchor="w",
                justify="left",
                font=ctk.CTkFont(
                    size=10,
                    weight="bold",
                ),
                text_color="#FFFFFF",
            ).pack(
                fill="x",
                padx=8,
                pady=(7, 1),
            )

            ctk.CTkLabel(
                column,
                text=description,
                anchor="w",
                justify="left",
                wraplength=210,
                font=ctk.CTkFont(size=9),
                text_color="#7F8796",
            ).pack(
                fill="x",
                padx=8,
                pady=(0, 5),
            )

            option.pack(
                fill="x",
                padx=7,
                pady=(0, 7),
            )

            return column

        self.game_filter_menu = ctk.CTkOptionMenu(
            settings_row,
            values=[
                "Выключен",
                "TCP",
                "UDP",
                "TCP + UDP",
            ],
            command=self.change_game_filter,
            variable=self.game_filter_var,
            width=150,
        )

        make_setting_column(
            "Game Filter",
            "Фильтрация игрового трафика: выключена или применяется к TCP/UDP/обоим протоколам.",
            self.game_filter_menu,
        )

        self.ipset_menu = ctk.CTkOptionMenu(
            settings_row,
            values=[
                "Any — без фильтра",
                "None — только исключение",
                "Loaded — использовать список",
            ],
            command=self.change_ipset_mode,
            variable=self.ipset_mode_var,
            width=150,
        )

        make_setting_column(
            "IPSet Filter",
            "Определяет список IP: пустой список, служебное исключение или загруженный ipset-all.txt.",
            self.ipset_menu,
        )

        self.auto_update_menu = ctk.CTkOptionMenu(
            settings_row,
            values=[
                "Выключено",
                "Включено",
            ],
            command=self.change_auto_update,
            variable=self.auto_update_var,
            width=150,
        )

        make_setting_column(
            "Auto-Update Check",
            "Включает фоновую проверку новой версии Zapret через служебный флаг.",
            self.auto_update_menu,
        )

        self.btn_fakes = self.service_small_button(
            sections,
            "🧩 Active Fakes",
            self.open_fakes_dialog,
        )

        self.btn_fakes.pack(
            fill="x",
            pady=(6, 8),
        )

        # UPDATES
        ctk.CTkLabel(
            sections,
            text="ОБНОВЛЕНИЯ",
            font=ctk.CTkFont(
                size=10,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            pady=(2, 5),
        )

        update_row = ctk.CTkFrame(
            sections,
            fg_color="transparent",
        )

        update_row.pack(
            fill="x"
        )

        self.service_small_button(
            update_row,
            "IPSet",
            self.update_ipset,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 4),
        )

        self.service_small_button(
            update_row,
            "Hosts",
            self.update_hosts,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=4,
        )

        self.service_small_button(
            update_row,
            "Проверить обновления",
            self.check_updates,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 0),
        )

        # TOOLS
        ctk.CTkLabel(
            sections,
            text="ИНСТРУМЕНТЫ",
            font=ctk.CTkFont(
                size=10,
                weight="bold",
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            pady=(10, 5),
        )

        tools_row = ctk.CTkFrame(
            sections,
            fg_color="transparent",
        )

        tools_row.pack(
            fill="x"
        )

        self.service_small_button(
            tools_row,
            "🔍 Диагностика",
            self.run_diagnostics,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 4),
        )

        self.service_small_button(
            tools_row,
            "🧪 Тесты",
            self.run_service_tests,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=4,
        )

        self.service_small_button(
            tools_row,
            "📂 Открыть папку",
            self.open_current_folder,
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 0),
        )

        self.service_details = ctk.CTkTextbox(
            self.service_card,
            height=100,
            fg_color="#15161D",
            border_color="#2E3240",
            border_width=1,
            text_color="#9CA3AF",
            font=ctk.CTkFont(size=10),
            wrap="word",
        )

        self.service_details.pack(
            fill="x",
            padx=14,
            pady=(0, 12),
        )

        self.service_details.insert(
            "1.0",
            "Проверка состояния сервиса..."
        )

        self.service_details.configure(
            state="disabled"
        )

    @staticmethod
    def service_button(
        parent,
        text,
        color,
        command,
    ):
        hover = (
            "#2563EB"
            if color == "#3B82F6"
            else (
                "#DC2626"
                if color == "#EF4444"
                else (
                    "#059669"
                    if color == "#10B981"
                    else (
                        "#D97706"
                        if color == "#F59E0B"
                        else "#7C3AED"
                    )
                )
            )
        )

        return ctk.CTkButton(
            parent,
            text=text,
            font=ctk.CTkFont(
                size=11,
                weight="bold",
            ),
            fg_color=color,
            hover_color=hover,
            text_color="#FFFFFF",
            height=34,
            corner_radius=6,
            command=command,
        )

    @staticmethod
    def service_small_button(
        parent,
        text,
        command,
    ):
        return ctk.CTkButton(
            parent,
            text=text,
            font=ctk.CTkFont(
                size=10,
                weight="bold",
            ),
            fg_color="#2E3240",
            hover_color="#374151",
            text_color="#FFFFFF",
            height=30,
            corner_radius=6,
            command=command,
        )

    # ========================================================
    # FOLDER / VERSIONS
    # ========================================================

    def ask_for_folder(self):
        folder = filedialog.askdirectory(
            initialdir=(
                self.root_dir
                if os.path.isdir(self.root_dir)
                else os.path.expanduser("~")
            ),
            title="Выберите папку ALL_VERSIONS",
        )

        if folder:
            self.set_root_folder(folder)

        elif not os.path.isdir(self.root_dir):
            self.status_sub.configure(
                text="Папка Zapret не выбрана"
            )

    def set_root_folder(self, folder):
        self.root_dir = folder

        save_config(
            self.root_dir
        )

        self.selected_version.set("")
        self.selected_bat.set("")

        self.bat_ping_results.clear()

        self.render_versions_list()

        # Не обновляем Tray синхронно несколько раз.
        self.request_tray_refresh()

        self.status_sub.configure(
            text="Папка обновлена. Выберите версию."
        )

    # ========================================================
    # ICON
    # ========================================================

    def load_icon(self):
        version = self.selected_version.get().strip()

        if version:
            selected_icon = os.path.join(
                self.root_dir,
                version,
                "icon.ico",
            )

            if os.path.isfile(selected_icon):
                try:
                    return Image.open(
                        selected_icon
                    ).convert("RGBA")
                except Exception:
                    pass

        if os.path.isdir(self.root_dir):
            try:
                for version_name in os.listdir(
                    self.root_dir
                ):
                    icon_path = os.path.join(
                        self.root_dir,
                        version_name,
                        "icon.ico",
                    )

                    if os.path.isfile(icon_path):
                        try:
                            return Image.open(
                                icon_path
                            ).convert("RGBA")
                        except Exception:
                            pass

            except Exception:
                pass

        return self.create_default_icon()

    @staticmethod
    def create_default_icon():
        image = Image.new(
            "RGB",
            (64, 64),
            (18, 19, 24),
        )

        draw = ImageDraw.Draw(image)

        draw.ellipse(
            (16, 16, 48, 48),
            fill=(16, 185, 129),
        )

        return image

    def update_window_icon(
        self,
        refresh_tray=True,
    ):
        try:
            self.icon_image = self.load_icon()

            temp_dir = (
                os.getenv("TEMP")
                or os.path.expanduser("~")
            )

            self.temp_icon_path = os.path.join(
                temp_dir,
                "zapret_manager_icon.ico",
            )

            self.icon_image.save(
                self.temp_icon_path,
                format="ICO",
            )

            self.iconbitmap(
                self.temp_icon_path
            )

        except Exception:
            pass

        if refresh_tray:
            self.request_tray_refresh()

    # ========================================================
    # VERSION LIST
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

            ctk.CTkLabel(
                self.version_scroll_frame,
                text="Папка не найдена",
                text_color="#EF4444",
            ).pack(
                pady=10
            )

            self.clear_bat_list()

            return

        try:
            root_items = os.listdir(
                self.root_dir
            )

        except Exception as exc:
            ctk.CTkLabel(
                self.version_scroll_frame,
                text=f"Ошибка чтения папки:\n{exc}",
                text_color="#EF4444",
                wraplength=220,
            ).pack(
                pady=10
            )

            return

        for item_name in sorted(
            root_items,
            key=str.lower,
        ):
            path = os.path.join(
                self.root_dir,
                item_name,
            )

            if not os.path.isdir(path):
                continue

            bats = get_bat_files(path)

            if bats:
                self.versions_data[item_name] = bats

        found = list(
            self.versions_data.keys()
        )

        if not found:
            self.selected_version.set("")
            self.selected_bat.set("")

            ctk.CTkLabel(
                self.version_scroll_frame,
                text="Версии не найдены",
                text_color="#F59E0B",
            ).pack(
                pady=10
            )

            self.clear_bat_list()

            # ВАЖНО:
            # Никаких sc query здесь.
            self.request_service_refresh(
                include_details=False
            )

            return

        current = self.selected_version.get()

        if current not in found:
            current = found[0]

            self.selected_version.set(
                current
            )

            self.selected_bat.set("")

        for version_name in found:

            selected = (
                version_name
                == self.selected_version.get()
            )

            button = ctk.CTkButton(
                self.version_scroll_frame,
                text=f"📂 {version_name}",
                anchor="w",
                font=ctk.CTkFont(
                    size=12,
                    weight="bold"
                    if selected
                    else "normal",
                ),
                height=34,
                corner_radius=6,
                fg_color=(
                    "#8B5CF6"
                    if selected
                    else "transparent"
                ),
                border_color=(
                    "#8B5CF6"
                    if selected
                    else "#2E3240"
                ),
                border_width=1,
                text_color=(
                    "#FFFFFF"
                    if selected
                    else "#9CA3AF"
                ),
                hover_color=(
                    "#7C3AED"
                    if selected
                    else "#1E2029"
                ),
                command=lambda v=version_name:
                    self.select_version(v),
            )

            button.pack(
                fill="x",
                pady=2,
            )

            self.version_buttons[
                version_name
            ] = button

        self.update_bat_list()

        # Только один запрос фонового состояния.
        self.request_service_refresh(
            include_details=False
        )

    # ========================================================
    # SELECT VERSION
    # ========================================================

    def select_version(self, version_name):

        if (
            self.testing_all
            or version_name not in self.versions_data
        ):
            return

        if (
            self.selected_version.get()
            == version_name
        ):
            return

        self.selected_version.set(
            version_name
        )

        self.bat_ping_results.clear()

        bats = self.versions_data.get(
            version_name,
            [],
        )

        selected_bat = (
            self.selected_bat.get()
        )

        if selected_bat not in bats:
            self.selected_bat.set(
                bats[0] if bats else ""
            )

        # ----------------------------------------------------
        # Быстро обновляем только визуальное состояние кнопок
        # ----------------------------------------------------

        for name, button in self.version_buttons.items():

            selected = (
                name == version_name
            )

            button.configure(
                fg_color=(
                    "#8B5CF6"
                    if selected
                    else "transparent"
                ),
                border_color=(
                    "#8B5CF6"
                    if selected
                    else "#2E3240"
                ),
                text_color=(
                    "#FFFFFF"
                    if selected
                    else "#9CA3AF"
                ),
                font=ctk.CTkFont(
                    size=12,
                    weight=(
                        "bold"
                        if selected
                        else "normal"
                    ),
                ),
                hover_color=(
                    "#7C3AED"
                    if selected
                    else "#1E2029"
                ),
            )

        # ----------------------------------------------------
        # Перестраиваем только список BAT.
        # ----------------------------------------------------

        self.update_bat_list()

        # ----------------------------------------------------
        # Читаем маленькие настройки.
        # Это обычный локальный файл и происходит быстро.
        # ----------------------------------------------------

        self.refresh_service_options()

        self.status_sub.configure(
            text=(
                f"Версия: {version_name} | "
                f"Выберите обход"
            )
        )

        # ----------------------------------------------------
        # НЕ вызываем refresh_tray() сразу.
        # ----------------------------------------------------

        self.request_tray_refresh()

        # Иконку можно обновить после обработки клика.
        # Она не блокирует сам обработчик выбора.
        self.after(
            150,
            self._update_icon_after_selection,
            version_name,
        )

    def _update_icon_after_selection(
        self,
        version_name,
    ):
        if self.closing:
            return

        if (
            self.selected_version.get()
            != version_name
        ):
            return

        # Не перестраиваем Tray.
        self.update_window_icon(
            refresh_tray=False
        )

    # ========================================================
    # BAT LIST
    # ========================================================

    def clear_bat_list(self):

        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.bat_cards.clear()

    def update_bat_list(self):

        self.clear_bat_list()

        version = self.selected_version.get()

        bats = self.versions_data.get(
            version,
            [],
        )

        if not version or not bats:
            return

        if self.selected_bat.get() not in bats:
            self.selected_bat.set(
                bats[0]
            )

        for bat_name in bats:
            self.create_bat_card(
                bat_name
            )

        # ВАЖНО:
        # Здесь больше НЕТ refresh_tray().
        #
        # Раньше select_version()
        # -> update_bat_list()
        # -> refresh_tray()
        # -> select_version()
        # -> refresh_tray()
        #
        # Это могло вызывать заметный фриз.

    def create_bat_card(self, bat_name):

        selected = (
            bat_name
            == self.selected_bat.get()
        )

        result = self.bat_ping_results.get(
            bat_name
        )

        card = ctk.CTkFrame(
            self.scroll_frame,
            fg_color=(
                "#10B981"
                if selected
                else "transparent"
            ),
            border_color=(
                "#10B981"
                if selected
                else "#2E3240"
            ),
            border_width=1,
            corner_radius=7,
            cursor="hand2",
        )

        card.pack(
            fill="x",
            pady=2,
        )

        card.bind(
            "<Button-1>",
            lambda e, b=bat_name:
                self.select_bat(b),
        )

        name_label = ctk.CTkLabel(
            card,
            text=f"📄 {bat_name}",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(
                size=12,
                weight=(
                    "bold"
                    if selected
                    else "normal"
                ),
            ),
            text_color=(
                "#FFFFFF"
                if selected
                else "#9CA3AF"
            ),
            wraplength=560,
        )

        name_label.pack(
            fill="x",
            padx=10,
            pady=(7, 2),
        )

        name_label.bind(
            "<Button-1>",
            lambda e, b=bat_name:
                self.select_bat(b),
        )

        result_label = ctk.CTkLabel(
            card,
            text="",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(
                size=10,
                weight="bold",
            ),
            text_color=(
                "#D1FAE5"
                if selected
                else "#9CA3AF"
            ),
            wraplength=560,
        )

        result_label.pack(
            fill="x",
            padx=10,
            pady=(0, 7),
        )

        result_label.bind(
            "<Button-1>",
            lambda e, b=bat_name:
                self.select_bat(b),
        )

        self.bat_cards[bat_name] = {
            "frame": card,
            "name": name_label,
            "result": result_label,
        }

        self._set_bat_card_result(
            bat_name,
            result=result,
        )

    def _set_bat_card_result(
        self,
        bat_name,
        result=None,
        status=None,
    ):
        item_data = self.bat_cards.get(
            bat_name
        )

        if not item_data:
            return

        if status is not None:
            text = status

        elif result is not None:
            yt = result.get("youtube")
            dc = result.get("discord")

            yt_text = (
                f"YouTube: {yt} ms"
                if yt is not None
                else "YouTube: ❌"
            )

            dc_text = (
                f"Discord: {dc} ms"
                if dc is not None
                else "Discord: ❌"
            )

            text = (
                f"{yt_text}    "
                f"{dc_text}"
            )

        else:
            text = (
                "YouTube: -- ms    "
                "Discord: -- ms"
            )

        item_data[
            "result"
        ].configure(
            text=text
        )

    def refresh_bat_card(
        self,
        bat_name,
        status=None,
    ):
        if bat_name not in self.bat_cards:
            return

        if status is not None:
            self._set_bat_card_result(
                bat_name,
                status=status,
            )
        else:
            self._set_bat_card_result(
                bat_name,
                result=self.bat_ping_results.get(
                    bat_name
                ),
            )

    def update_bat_selection_visuals(self):

        selected_name = (
            self.selected_bat.get()
        )

        for bat_name, data in self.bat_cards.items():

            selected = (
                bat_name
                == selected_name
            )

            data["frame"].configure(
                fg_color=(
                    "#10B981"
                    if selected
                    else "transparent"
                ),
                border_color=(
                    "#10B981"
                    if selected
                    else "#2E3240"
                ),
            )

            data["name"].configure(
                text_color=(
                    "#FFFFFF"
                    if selected
                    else "#9CA3AF"
                ),
                font=ctk.CTkFont(
                    size=12,
                    weight=(
                        "bold"
                        if selected
                        else "normal"
                    ),
                ),
            )

            data["result"].configure(
                text_color=(
                    "#D1FAE5"
                    if selected
                    else "#9CA3AF"
                )
            )

    # ========================================================
    # SELECT BAT
    # ========================================================

    def select_bat(self, bat_name):

        if (
            self.testing_all
            or bat_name
            not in self.versions_data.get(
                self.selected_version.get(),
                [],
            )
        ):
            return

        if (
            self.selected_bat.get()
            == bat_name
        ):
            return

        self.selected_bat.set(
            bat_name
        )

        # Только визуальное изменение.
        self.update_bat_selection_visuals()

        self.status_sub.configure(
            text=(
                f"Версия: "
                f"{self.selected_version.get()} | "
                f"Обход: {bat_name}"
            )
        )

        # ----------------------------------------------------
        # КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ:
        #
        # НИКАКОГО refresh_tray() здесь.
        #
        # Именно выбор BAT раньше мог ощущаться как
        # "подвисание", потому что pystray строил меню
        # прямо во время обработки клика.
        # ----------------------------------------------------

    def get_current_paths(self):

        version = self.selected_version.get()

        if not version:
            return None, None

        version_path = os.path.join(
            self.root_dir,
            version,
        )

        if not os.path.isdir(
            version_path
        ):
            return None, None

        service_path = os.path.join(
            version_path,
            "service.bat",
        )

        return (
            version_path,
            service_path
            if os.path.isfile(service_path)
            else None,
        )

    # ========================================================
    # BAT TESTING
    # ========================================================

    def launch_bat(
        self,
        bat_path,
        cwd,
        hidden=False,
    ):
        try:
            kwargs = {
                "cwd": cwd,
                "stdout": (
                    subprocess.DEVNULL
                    if hidden
                    else None
                ),
                "stderr": (
                    subprocess.DEVNULL
                    if hidden
                    else None
                ),
            }

            if hidden:
                kwargs["creationflags"] = (
                    HIDDEN_WINDOW_FLAG
                )

                kwargs["startupinfo"] = (
                    create_no_window_startupinfo()
                )

            return subprocess.Popen(
                [
                    "cmd.exe",
                    "/c",
                    "call",
                    bat_path,
                ],
                **kwargs,
            )

        except Exception:
            return None

    def test_single_bat(
        self,
        version_path,
        bat_name,
        progress_callback=None,
    ):
        bat_path = os.path.join(
            version_path,
            bat_name,
        )

        if not os.path.isfile(bat_path):
            return {
                "status": "launch_error",
                "error": "BAT файл не найден",
                "youtube": None,
                "discord": None,
                "pids": [],
            }

        if progress_callback:
            progress_callback(
                "⏳ Остановка старых процессов..."
            )

        old_pids = set(
            get_winws_pids()
        )

        if old_pids:
            kill_winws()

            wait_until_no_winws(
                PROCESS_STOP_TIMEOUT
            )

        if progress_callback:
            progress_callback(
                "⏳ Запуск..."
            )

        proc = self.launch_bat(
            bat_path,
            version_path,
            hidden=True,
        )

        if proc is None:
            return {
                "status": "launch_error",
                "error": "Не удалось запустить BAT",
                "youtube": None,
                "discord": None,
                "pids": [],
            }

        if progress_callback:
            progress_callback(
                "⏳ Ожидание winws.exe..."
            )

        new_pids = set()

        end = (
            time.monotonic()
            + WINWS_START_TIMEOUT
        )

        while time.monotonic() < end:

            if (
                self.shutdown_event.is_set()
                or self.test_cancel_event.is_set()
            ):
                break

            time.sleep(
                WINWS_POLL_INTERVAL
            )

            current = set(
                get_winws_pids()
            )

            new_pids = (
                current - old_pids
            )

            if new_pids:
                break

        if not new_pids:

            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass

            return {
                "status": "launch_error",
                "error": "winws.exe не появился",
                "youtube": None,
                "discord": None,
                "pids": [],
            }

        if (
            self.shutdown_event.is_set()
            or self.test_cancel_event.is_set()
        ):

            for pid in new_pids:
                kill_process_by_pid(pid)

            return {
                "status": "cancelled",
                "youtube": None,
                "discord": None,
                "pids": list(new_pids),
            }

        if progress_callback:
            progress_callback(
                "⏳ YouTube..."
            )

        yt = check_tcp_ping(
            "www.youtube.com"
        )

        if (
            self.shutdown_event.is_set()
            or self.test_cancel_event.is_set()
        ):

            for pid in new_pids:
                kill_process_by_pid(pid)

            return {
                "status": "cancelled",
                "youtube": yt,
                "discord": None,
                "pids": list(new_pids),
            }

        if progress_callback:
            progress_callback(
                "⏳ Discord..."
            )

        dc = check_tcp_ping(
            "discord.com"
        )

        if progress_callback:
            progress_callback(
                "⏳ Остановка..."
            )

        for pid in new_pids:
            kill_process_by_pid(pid)

        start = time.monotonic()

        while (
            time.monotonic() - start
            < PROCESS_STOP_TIMEOUT
        ):

            if not (
                set(get_winws_pids())
                & new_pids
            ):
                break

            time.sleep(
                WINWS_POLL_INTERVAL
            )

        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

        status = (
            "success"
            if yt is not None
            and dc is not None
            else (
                "partial"
                if yt is not None
                or dc is not None
                else "ping_error"
            )
        )

        return {
            "status": status,
            "youtube": yt,
            "discord": dc,
            "pids": list(new_pids),
        }

    def start_test_all(self):

        if self.testing_all:
            return

        version = (
            self.selected_version.get()
        )

        bats = self.versions_data.get(
            version,
            [],
        )

        if not version:
            messagebox.showwarning(
                "Внимание",
                "Сначала выберите версию.",
            )

            return

        if not bats:
            messagebox.showwarning(
                "Внимание",
                "В выбранной версии нет BAT-файлов.",
            )

            return

        self.testing_all = True
        self.stop_requested = False

        self.test_cancel_event.clear()
        self.shutdown_event.clear()

        self.bat_ping_results.clear()

        self.btn_test_all.configure(
            state="disabled",
            text="⏳ Тестируем...",
        )

        self.btn_start.configure(
            state="disabled"
        )

        self.btn_service_install.configure(
            state="disabled"
        )

        self.status_sub.configure(
            text="Тестирование всех BAT..."
        )

        self.update_bat_list()

        self.testing_thread = threading.Thread(
            target=self._test_all_worker,
            args=(
                version,
                list(bats),
            ),
            daemon=True,
        )

        self.testing_thread.start()

    def _test_all_worker(
        self,
        version,
        bats,
    ):
        version_path = os.path.join(
            self.root_dir,
            version,
        )

        for bat_name in bats:

            if (
                self.shutdown_event.is_set()
                or self.test_cancel_event.is_set()
            ):
                break

            self.after(
                0,
                self.update_bat_status,
                bat_name,
                "⏳ запуск...",
            )

            result = self.test_single_bat(
                version_path,
                bat_name,
                progress_callback=(
                    lambda status, b=bat_name:
                    self.after(
                        0,
                        self.update_bat_status,
                        b,
                        status,
                    )
                ),
            )

            self.after(
                0,
                self.update_bat_result,
                bat_name,
                result,
            )

            time.sleep(0.25)

        self.after(
            0,
            self.finish_test_all,
        )

    def update_bat_status(
        self,
        bat_name,
        status,
    ):
        self.refresh_bat_card(
            bat_name,
            status=status,
        )

    def update_bat_result(
        self,
        bat_name,
        result,
    ):
        self.bat_ping_results[
            bat_name
        ] = {
            "youtube": result.get(
                "youtube"
            ),
            "discord": result.get(
                "discord"
            ),
        }

        self.refresh_bat_card(
            bat_name
        )

    def finish_test_all(self):

        if self.closing:
            return

        self.testing_all = False
        self.stop_requested = False

        self.test_cancel_event.clear()
        self.shutdown_event.clear()

        self.btn_test_all.configure(
            state="normal",
            text="📊 Тест всех",
        )

        self.btn_start.configure(
            state="normal"
        )

        self.request_service_refresh(
            include_details=False
        )

        best = None
        best_score = None

        for name, res in self.bat_ping_results.items():

            yt = res.get("youtube")
            dc = res.get("discord")

            if (
                yt is not None
                and dc is not None
            ):
                score = yt + dc

                if (
                    best_score is None
                    or score < best_score
                ):
                    best_score = score
                    best = name

        if best:
            self.status_sub.configure(
                text=(
                    "Тестирование завершено. "
                    f"Лучший обход: {best}"
                )
            )

        else:
            self.status_sub.configure(
                text=(
                    "Тестирование завершено. "
                    "Нет BAT с полными данными пинга."
                )
            )

        self.update_bat_list()

        self.request_tray_refresh()

    # ========================================================
    # STANDALONE LAUNCHER
    # ========================================================

    def start_process(self):

        if (
            self.protection_starting
            or self.testing_all
        ):
            return

        version_path, _ = (
            self.get_current_paths()
        )

        bat_name = (
            self.selected_bat.get()
        )

        if not version_path:
            messagebox.showwarning(
                "Внимание",
                "Выберите версию Zapret.",
            )

            return

        if not bat_name:
            messagebox.showwarning(
                "Внимание",
                "Выберите BAT-файл обхода.",
            )

            return

        bat_path = os.path.join(
            version_path,
            bat_name,
        )

        if not os.path.isfile(bat_path):
            messagebox.showerror(
                "Ошибка",
                f"Файл не найден:\n{bat_path}",
            )

            return

        self.protection_starting = True

        self.btn_start.configure(
            state="disabled",
            text="Запуск...",
        )

        threading.Thread(
            target=self._start_process_worker,
            args=(
                version_path,
                bat_path,
            ),
            daemon=True,
        ).start()

    def _start_process_worker(
        self,
        version_path,
        bat_path,
    ):
        try:
            old_pids = set(
                get_winws_pids()
            )

            if old_pids:
                kill_winws()

                wait_until_no_winws(
                    PROCESS_STOP_TIMEOUT
                )

            proc = self.launch_bat(
                bat_path,
                version_path,
                hidden=False,
            )

            if proc is None:
                self.after(
                    0,
                    self._start_error,
                    "Не удалось запустить BAT",
                )

                return

            new_pids = set()

            end = (
                time.monotonic()
                + WINWS_START_TIMEOUT
            )

            while time.monotonic() < end:

                time.sleep(
                    WINWS_POLL_INTERVAL
                )

                current = set(
                    get_winws_pids()
                )

                new_pids = (
                    current - old_pids
                )

                if new_pids:
                    break

            if not new_pids:

                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass

                self.after(
                    0,
                    self._start_error,
                    "winws.exe не появился после запуска BAT",
                )

                return

            self.managed_pids = new_pids

            self.after(
                0,
                self._finish_start,
            )

        except Exception as exc:

            if not self.closing:
                self.after(
                    0,
                    self._start_error,
                    str(exc),
                )

    def _finish_start(self):

        if self.closing:
            return

        self.protection_starting = False

        self.btn_start.configure(
            state="normal",
            text="Запуск",
        )

        self.status_title.configure(
            text="● ЗАЩИТА АКТИВНА",
            text_color="#10B981",
        )

        self.status_sub.configure(
            text=(
                f"Версия: "
                f"{self.selected_version.get()} | "
                f"Обход: "
                f"{self.selected_bat.get()}"
            )
        )

        self.run_ping_check()

        self.request_tray_refresh()

        self.request_service_refresh(
            include_details=False
        )

    def _start_error(self, error):

        if self.closing:
            return

        self.protection_starting = False

        self.btn_start.configure(
            state="normal",
            text="Запуск",
        )

        self.status_title.configure(
            text="● ОШИБКА",
            text_color="#EF4444",
        )

        self.status_sub.configure(
            text="Ошибка запуска Zapret"
        )

        messagebox.showerror(
            "Ошибка запуска",
            error,
        )

    def stop_process(self):

        if self.stopping:
            return

        if self.testing_all:
            self.test_cancel_event.set()

            self.btn_stop.configure(
                state="disabled",
                text="Остановка...",
            )

            return

        self.stopping = True

        self.btn_stop.configure(
            state="disabled",
            text="Остановка...",
        )

        threading.Thread(
            target=self._stop_worker,
            daemon=True,
        ).start()

    def _stop_worker(self):

        for pid in set(
            self.managed_pids
        ):
            kill_process_by_pid(pid)

        self.managed_pids.clear()

        kill_winws()

        wait_until_no_winws(
            PROCESS_STOP_TIMEOUT
        )

        self.after(
            0,
            self._update_stop_ui,
        )

    def _update_stop_ui(self):

        if self.closing:
            return

        self.stopping = False

        self.btn_stop.configure(
            state="normal",
            text="Стоп",
        )

        self.status_title.configure(
            text="● ОСТАНОВЛЕНО",
            text_color="#EF4444",
        )

        self.status_sub.configure(
            text="Выберите версию и обход"
        )

        self.request_service_refresh(
            include_details=False
        )

    # ========================================================
    # PING
    # ========================================================

    def run_ping_check(self):

        if (
            self.testing_all
            or self.closing
        ):
            return

        self.btn_check_ping.configure(
            state="disabled",
            text="⏳...",
        )

        self.yt_ping_label.configure(
            text="YouTube: ...",
            text_color="#9CA3AF",
        )

        self.dc_ping_label.configure(
            text="Discord: ...",
            text_color="#9CA3AF",
        )

        threading.Thread(
            target=self._ping_worker,
            daemon=True,
        ).start()

    def _ping_worker(self):

        yt = check_tcp_ping(
            "www.youtube.com"
        )

        dc = check_tcp_ping(
            "discord.com"
        )

        if not self.closing:
            self.after(
                0,
                self._update_ping_ui,
                yt,
                dc,
            )

    def _update_ping_ui(
        self,
        yt,
        dc,
    ):
        if self.closing:
            return

        self.configure_ping_label(
            self.yt_ping_label,
            "YouTube",
            yt,
        )

        self.configure_ping_label(
            self.dc_ping_label,
            "Discord",
            dc,
        )

        self.btn_check_ping.configure(
            state="normal",
            text="⚡ Проверить",
        )

    @staticmethod
    def configure_ping_label(
        label,
        name,
        value,
    ):
        if (
            value is None
            or value > 2000
        ):
            label.configure(
                text=f"{name}: ❌ Ошибка",
                text_color="#EF4444",
            )

        else:
            color = (
                "#10B981"
                if value < 100
                else (
                    "#F59E0B"
                    if value < 200
                    else "#EF4444"
                )
            )

            label.configure(
                text=f"{name}: {value} ms",
                text_color=color,
            )

    # ========================================================
    # SERVICE UI - НОВАЯ АСИНХРОННАЯ СИСТЕМА
    # ========================================================

    def request_service_refresh(
        self,
        include_details=False,
    ):
        """
        Запрашивает обновление состояния сервиса.

        Главное отличие от старой версии:
        здесь НЕТ sc/tasklist/registry в GUI-потоке.

        Если несколько событий подряд вызывают обновление,
        они объединяются.
        """

        if self.closing:
            return

        self.service_refresh_generation += 1

        generation = (
            self.service_refresh_generation
        )

        if self.service_refresh_running:
            self.service_refresh_pending = (
                self.service_refresh_pending
                or include_details
            )

            return

        self.service_refresh_running = True

        threading.Thread(
            target=self._service_refresh_worker,
            args=(
                generation,
                include_details,
            ),
            daemon=True,
            name="ZapretServiceRefresh",
        ).start()

    def _service_refresh_worker(
        self,
        generation,
        include_details,
    ):
        try:
            # ----------------------------------------------
            # Все тяжёлые операции здесь.
            # ----------------------------------------------

            exists = (
                ServiceManager.service_exists()
            )

            status = None
            strategy = None

            if exists:
                status = (
                    ServiceManager.get_service_status()
                )

                strategy = (
                    ServiceManager.get_service_strategy()
                )

            winws_running = is_winws_running()

            details = None

            if include_details:
                details = (
                    ServiceManager.get_service_diagnostic()
                )

            result = {
                "exists": exists,
                "status": status,
                "strategy": strategy,
                "winws_running": winws_running,
                "details": details,
                "generation": generation,
            }

            if not self.closing:
                self.after(
                    0,
                    self._apply_service_refresh,
                    result,
                )

        except Exception as exc:

            if not self.closing:
                self.after(
                    0,
                    self._service_refresh_error,
                    str(exc),
                    generation,
                )

    def _apply_service_refresh(
        self,
        result,
    ):
        if self.closing:
            return

        generation = result.get(
            "generation"
        )

        # Если уже пришёл более новый запрос,
        # старый результат не применяем.
        if generation != self.service_refresh_generation:
            self.service_refresh_running = False

            if self.service_refresh_pending:
                pending_details = (
                    self.service_refresh_pending
                )

                self.service_refresh_pending = False

                self.request_service_refresh(
                    include_details=pending_details
                )

            return

        exists = result["exists"]
        status = result["status"]
        strategy = result["strategy"]
        winws_running = result["winws_running"]
        details = result["details"]

        if not exists:

            self.service_status_label.configure(
                text="○ Сервис НЕ установлен",
                text_color="#EF4444",
            )

            selected = (
                normalize_bat_name(
                    self.selected_bat.get()
                )
                if self.selected_bat.get()
                else "не выбрана"
            )

            self.service_strategy_label.configure(
                text=(
                    "Установка будет использовать: "
                    f"{selected}"
                )
            )

        elif status == "RUNNING":

            self.service_status_label.configure(
                text="● Сервис ЗАПУЩЕН",
                text_color="#10B981",
            )

            self.service_strategy_label.configure(
                text=(
                    f"Стратегия: "
                    f"{strategy or 'не установлена'}"
                )
            )

        elif status == "STOPPED":

            self.service_status_label.configure(
                text="● Сервис ОСТАНОВЛЕН",
                text_color="#F59E0B",
            )

            self.service_strategy_label.configure(
                text=(
                    f"Стратегия: "
                    f"{strategy or 'не установлена'}"
                )
            )

        elif status == "START_PENDING":

            self.service_status_label.configure(
                text="⏳ Сервис запускается...",
                text_color="#10B981",
            )

            self.service_strategy_label.configure(
                text=(
                    f"Стратегия: "
                    f"{strategy or 'не установлена'}"
                )
            )

        elif status == "STOP_PENDING":

            self.service_status_label.configure(
                text="⏳ Сервис останавливается...",
                text_color="#F59E0B",
            )

            self.service_strategy_label.configure(
                text=(
                    f"Стратегия: "
                    f"{strategy or 'не установлена'}"
                )
            )

        else:

            self.service_status_label.configure(
                text=(
                    f"● Статус: "
                    f"{status or 'UNKNOWN'}"
                ),
                text_color="#9CA3AF",
            )

            self.service_strategy_label.configure(
                text=(
                    f"Стратегия: "
                    f"{strategy or 'не установлена'}"
                )
            )

        self.service_process_label.configure(
            text=(
                f"winws.exe: "
                f"{'РАБОТАЕТ' if winws_running else 'НЕ запущен'}"
            ),
            text_color=(
                "#10B981"
                if winws_running
                else "#9CA3AF"
            ),
        )

        self.btn_service_install.configure(
            state=(
                "disabled"
                if (
                    self.testing_all
                    or self.service_operation_in_progress
                )
                else "normal"
            ),
            text=(
                "🔄 Переустановить сервис"
                if exists
                else "📥 Установить сервис"
            ),
        )

        self.btn_service_delete.configure(
            state=(
                "normal"
                if exists
                and not self.testing_all
                else "disabled"
            )
        )

        self.btn_service_start.configure(
            state=(
                "normal"
                if exists
                and status not in (
                    "RUNNING",
                    "START_PENDING",
                )
                and not self.testing_all
                else "disabled"
            )
        )

        self.btn_service_stop.configure(
            state=(
                "normal"
                if exists
                and status in (
                    "RUNNING",
                    "START_PENDING",
                )
                and not self.testing_all
                else "disabled"
            )
        )

        self.btn_service_restart.configure(
            state=(
                "normal"
                if exists
                and not self.testing_all
                else "disabled"
            )
        )

        if details is not None:
            self._set_service_details(
                details
            )

        self.service_refresh_running = False

        if self.service_refresh_pending:

            pending_details = (
                self.service_refresh_pending
            )

            self.service_refresh_pending = False

            self.request_service_refresh(
                include_details=pending_details
            )

    def _service_refresh_error(
        self,
        error,
        generation,
    ):
        if self.closing:
            return

        self.service_refresh_running = False

        # Не показываем временную ошибку поверх рабочего интерфейса
        # от устаревшего потока.
        if generation == self.service_refresh_generation:
            print(
                "Ошибка фонового обновления сервиса:",
                error,
            )

        if self.service_refresh_pending:
            pending_details = (
                self.service_refresh_pending
            )

            self.service_refresh_pending = False

            self.request_service_refresh(
                include_details=pending_details
            )

    def refresh_service_ui(
        self,
        include_details=True,
    ):
        """
        Совместимый публичный метод.

        Старый код мог вызывать refresh_service_ui().
        Теперь он просто ставит асинхронный запрос.
        """

        self.request_service_refresh(
            include_details=include_details
        )

    def _set_service_details(
        self,
        text,
    ):
        if self.closing:
            return

        self.service_details.configure(
            state="normal"
        )

        self.service_details.delete(
            "1.0",
            "end",
        )

        self.service_details.insert(
            "1.0",
            text,
        )

        self.service_details.configure(
            state="disabled"
        )

    def update_service_details(self):
        # Совместимость со старым кодом.
        self.request_service_refresh(
            include_details=True
        )

    def start_service_status_polling(self):

        if self.closing:
            return

        self.request_service_refresh(
            include_details=False
        )

        self.service_refresh_after_id = (
            self.after(
                3000,
                self.start_service_status_polling,
            )
        )

    # ========================================================
    # SERVICE ACTIONS
    # ========================================================

    def install_service(self):

        if not is_admin():
            messagebox.showerror(
                "Ошибка",
                "Для управления сервисом нужны права администратора.",
            )

            return

        if (
            self.testing_all
            or self.service_operation_in_progress
        ):
            return

        version_path, _ = (
            self.get_current_paths()
        )

        bat_name = (
            self.selected_bat.get()
        )

        if (
            not version_path
            or not bat_name
        ):
            messagebox.showwarning(
                "Внимание",
                "Выберите версию и BAT-файл.",
            )

            return

        bat_path = os.path.join(
            version_path,
            bat_name,
        )

        bin_path = os.path.join(
            version_path,
            "bin",
            "winws.exe",
        )

        if not os.path.isfile(bat_path):
            messagebox.showerror(
                "Ошибка",
                f"BAT файл не найден:\n{bat_path}",
            )

            return

        if not os.path.isfile(bin_path):
            messagebox.showerror(
                "Ошибка",
                f"winws.exe не найден:\n{bin_path}",
            )

            return

        args, error = parse_bat_winws_args(
            bat_path,
            version_path,
        )

        if error:
            messagebox.showerror(
                "Ошибка разбора BAT",
                error,
            )

            return

        existing_note = (
            "\nТекущий сервис будет остановлен, "
            "удалён и создан заново."
            if ServiceManager.service_exists()
            else ""
        )

        confirm = messagebox.askyesno(
            "Установить сервис",
            f"Будет установлен Windows Service 'zapret'.\n\n"
            f"Стратегия: {normalize_bat_name(bat_name)}\n"
            f"winws.exe:\n{bin_path}\n\n"
            f"Аргументы:\n{args or '(нет)'}\n\n"
            f"После создания сервис будет автоматически запущен."
            f"{existing_note}",
        )

        if not confirm:
            return

        self.service_operation_in_progress = True

        self.btn_service_install.configure(
            state="disabled",
            text="⏳ Установка...",
        )

        self.btn_service_delete.configure(
            state="disabled"
        )

        self.btn_service_start.configure(
            state="disabled"
        )

        self.btn_service_stop.configure(
            state="disabled"
        )

        self.btn_service_restart.configure(
            state="disabled"
        )

        def worker():
            ok, msg = ServiceManager.install_service(
                bin_path,
                args,
                bat_name,
                version_path,
            )

            self.after(
                0,
                self._install_service_complete,
                ok,
                msg,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def _install_service_complete(
        self,
        ok,
        msg,
    ):
        self.service_operation_in_progress = False

        self.btn_service_install.configure(
            text="📥 Установить сервис"
        )

        if ok:
            messagebox.showinfo(
                "Успех",
                msg,
            )

        else:
            messagebox.showerror(
                "Ошибка установки сервиса",
                msg,
            )

        self.request_service_refresh(
            include_details=True
        )

    def delete_service(self):

        if self.testing_all:
            return

        if not messagebox.askyesno(
            "Удалить сервис",
            "Удалить сервис zapret и остановить связанные процессы?",
        ):
            return

        self.btn_service_delete.configure(
            state="disabled",
            text="⏳ Удаление...",
        )

        def worker():

            ok, msg = (
                ServiceManager.delete_service()
            )

            kill_winws()

            wait_until_no_winws(
                PROCESS_STOP_TIMEOUT
            )

            self.after(
                0,
                self._delete_service_complete,
                ok,
                msg,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def _delete_service_complete(
        self,
        ok,
        msg,
    ):
        self.btn_service_delete.configure(
            text="🗑 Удалить"
        )

        if ok:
            messagebox.showinfo(
                "Готово",
                msg,
            )

        else:
            messagebox.showerror(
                "Ошибка",
                msg,
            )

        self.request_service_refresh(
            include_details=True
        )

    def start_service(self):

        if self.testing_all:
            return

        self.btn_service_start.configure(
            state="disabled",
            text="⏳ Запуск...",
        )

        def worker():

            ok, msg = (
                ServiceManager.start_service()
            )

            self.after(
                0,
                self._service_action_complete,
                self.btn_service_start,
                "▶ Запустить",
                ok,
                msg,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def stop_service(self):

        if self.testing_all:
            return

        self.btn_service_stop.configure(
            state="disabled",
            text="⏳ Остановка...",
        )

        def worker():

            ok, msg = (
                ServiceManager.stop_service()
            )

            self.after(
                0,
                self._service_action_complete,
                self.btn_service_stop,
                "⏹ Остановить",
                ok,
                msg,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def restart_service(self):

        if self.testing_all:
            return

        self.btn_service_restart.configure(
            state="disabled",
            text="⏳ Перезапуск...",
        )

        def worker():

            ok, msg = (
                ServiceManager.restart_service()
            )

            self.after(
                0,
                self._service_action_complete,
                self.btn_service_restart,
                "🔄 Перезапустить",
                ok,
                msg,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

    def _service_action_complete(
        self,
        button,
        default_text,
        ok,
        msg,
    ):
        button.configure(
            state="normal",
            text=default_text,
        )

        if not ok:
            messagebox.showerror(
                "Ошибка сервиса",
                msg,
            )

        self.request_service_refresh(
            include_details=True
        )

    # ========================================================
    # SERVICE.BAT SETTINGS
    # ========================================================

    def get_utils_path(self, name):
        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return None

        return os.path.join(
            version_path,
            "utils",
            name,
        )

    def get_lists_path(self, name):
        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return None

        return os.path.join(
            version_path,
            "lists",
            name,
        )

    def change_game_filter(
        self,
        value,
    ):
        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        flag = os.path.join(
            version_path,
            "utils",
            "game_filter.enabled",
        )

        try:
            os.makedirs(
                os.path.dirname(flag),
                exist_ok=True,
            )

            if value in (
                "disabled",
                "Выключен",
            ):

                if os.path.exists(flag):
                    os.remove(flag)

            else:

                mode = (
                    "all"
                    if value == "TCP + UDP"
                    else value.lower()
                )

                with open(
                    flag,
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(mode)

            messagebox.showinfo(
                "Game Filter",
                "Настройка сохранена. "
                "Перезапустите Zapret, чтобы применить изменения.",
            )

        except Exception as exc:
            messagebox.showerror(
                "Ошибка",
                str(exc),
            )

        self.request_service_refresh(
            include_details=False
        )

    def change_ipset_mode(
        self,
        value,
    ):
        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        list_file = os.path.join(
            version_path,
            "lists",
            "ipset-all.txt",
        )

        backup = (
            list_file
            + ".backup"
        )

        try:
            os.makedirs(
                os.path.dirname(list_file),
                exist_ok=True,
            )

            if (
                value == "none"
                or value.startswith("None")
            ):

                if os.path.exists(list_file):
                    if os.path.exists(backup):
                        os.remove(backup)

                    os.replace(
                        list_file,
                        backup,
                    )

                with open(
                    list_file,
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write(
                        "203.0.113.113/32\n"
                    )

            elif (
                value == "any"
                or value.startswith("Any")
            ):

                with open(
                    list_file,
                    "w",
                    encoding="utf-8",
                ):
                    pass

            elif (
                value == "loaded"
                or value.startswith("Loaded")
            ):

                if os.path.exists(backup):

                    if os.path.exists(list_file):
                        os.remove(list_file)

                    os.replace(
                        backup,
                        list_file,
                    )

                elif not os.path.exists(list_file):

                    messagebox.showwarning(
                        "IPSet",
                        "Backup-файл отсутствует. "
                        "Сначала обновите IPSet.",
                    )

                    return

            messagebox.showinfo(
                "IPSet",
                "Режим IPSet изменён.",
            )

        except Exception as exc:
            messagebox.showerror(
                "Ошибка IPSet",
                str(exc),
            )

        self.request_service_refresh(
            include_details=False
        )

    def change_auto_update(
        self,
        value,
    ):
        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        flag = os.path.join(
            version_path,
            "utils",
            "check_updates.enabled",
        )

        try:
            os.makedirs(
                os.path.dirname(flag),
                exist_ok=True,
            )

            if (
                value == "enabled"
                or value == "Включено"
            ):
                Path(flag).write_text(
                    "ENABLED\n",
                    encoding="utf-8",
                )

            elif os.path.exists(flag):
                os.remove(flag)

        except Exception as exc:
            messagebox.showerror(
                "Ошибка",
                str(exc),
            )

        self.request_service_refresh(
            include_details=False
        )

    def refresh_service_options(self):

        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        game_flag = os.path.join(
            version_path,
            "utils",
            "game_filter.enabled",
        )

        update_flag = os.path.join(
            version_path,
            "utils",
            "check_updates.enabled",
        )

        list_file = os.path.join(
            version_path,
            "lists",
            "ipset-all.txt",
        )

        mode = "disabled"

        try:
            if os.path.isfile(game_flag):
                gm = Path(
                    game_flag
                ).read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).strip().lower()

                mode = (
                    "TCP + UDP"
                    if gm == "all"
                    else gm.upper()
                )

        except Exception:
            pass

        if mode not in [
            "disabled",
            "TCP",
            "UDP",
            "TCP + UDP",
        ]:
            mode = "disabled"

        game_display = {
            "disabled": "Выключен",
            "TCP": "TCP",
            "UDP": "UDP",
            "TCP + UDP": "TCP + UDP",
        }

        self.game_filter_var.set(
            game_display.get(
                mode,
                "Выключен",
            )
        )

        self.auto_update_var.set(
            "Включено"
            if os.path.exists(update_flag)
            else "Выключено"
        )

        try:
            content = (
                Path(list_file).read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
                if os.path.isfile(list_file)
                else ""
            )

            if not content.strip():
                ipmode = "any"

            elif (
                "203.0.113.113/32"
                in content
            ):
                ipmode = "none"

            else:
                ipmode = "loaded"

        except Exception:
            ipmode = "any"

        ip_display = {
            "any": "Any — без фильтра",
            "none": "None — только исключение",
            "loaded": "Loaded — использовать список",
        }

        self.ipset_mode_var.set(
            ip_display.get(
                ipmode,
                "Any — без фильтра",
            )
        )

    # ========================================================
    # ACTIVE FAKES
    # ========================================================

    def open_fakes_dialog(self):

        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        bin_dir = os.path.join(
            version_path,
            "bin",
        )

        if not os.path.isdir(bin_dir):
            messagebox.showerror(
                "Active Fakes",
                "Папка bin не найдена.",
            )

            return

        active_discord = os.path.join(
            bin_dir,
            "ACTIVE_DISCORD_UDP.bin",
        )

        active_game = os.path.join(
            bin_dir,
            "ACTIVE_GAME_UDP.bin",
        )

        fake_files = [
            p
            for p in Path(bin_dir).glob("*.bin")
            if not p.name.upper().startswith(
                "ACTIVE_"
            )
        ]

        fake_files = sorted(
            fake_files,
            key=lambda p: p.name.lower(),
        )

        if not fake_files:
            messagebox.showinfo(
                "Active Fakes",
                "В папке bin не найдены fake .bin файлы.",
            )

            return

        win = ctk.CTkToplevel(
            self
        )

        win.title(
            "Active Fakes"
        )

        win.geometry(
            "520x380"
        )

        win.configure(
            fg_color="#121318"
        )

        win.grab_set()

        ctk.CTkLabel(
            win,
            text="Замена активных fake-файлов",
            font=ctk.CTkFont(
                size=15,
                weight="bold",
            ),
        ).pack(
            pady=(16, 10)
        )

        def sha256(path):
            import hashlib

            h = hashlib.sha256()

            try:
                with open(
                    path,
                    "rb",
                ) as f:

                    for chunk in iter(
                        lambda: f.read(
                            1024 * 1024
                        ),
                        b"",
                    ):
                        h.update(chunk)

                return h.hexdigest()

            except Exception:
                return None

        current_discord_hash = (
            sha256(active_discord)
            if os.path.isfile(active_discord)
            else None
        )

        current_game_hash = (
            sha256(active_game)
            if os.path.isfile(active_game)
            else None
        )

        discord_current = next(
            (
                p.name
                for p in fake_files
                if sha256(str(p))
                == current_discord_hash
            ),
            "не найден",
        )

        game_current = next(
            (
                p.name
                for p in fake_files
                if sha256(str(p))
                == current_game_hash
            ),
            "не найден",
        )

        ctk.CTkLabel(
            win,
            text=(
                f"Discord UDP: "
                f"{discord_current}"
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            padx=18,
        )

        ctk.CTkLabel(
            win,
            text=(
                f"Game UDP: "
                f"{game_current}"
            ),
            text_color="#9CA3AF",
        ).pack(
            anchor="w",
            padx=18,
            pady=(0, 8),
        )

        names = [
            p.name
            for p in fake_files
        ]

        fake_var1 = tk.StringVar(
            value=names[0]
        )

        fake_var2 = tk.StringVar(
            value=names[0]
        )

        ctk.CTkLabel(
            win,
            text="Discord UDP →",
            text_color="#FFFFFF",
        ).pack(
            anchor="w",
            padx=18,
            pady=(6, 2),
        )

        ctk.CTkOptionMenu(
            win,
            variable=fake_var1,
            values=names,
        ).pack(
            fill="x",
            padx=18,
        )

        ctk.CTkLabel(
            win,
            text="Game UDP →",
            text_color="#FFFFFF",
        ).pack(
            anchor="w",
            padx=18,
            pady=(8, 2),
        )

        ctk.CTkOptionMenu(
            win,
            variable=fake_var2,
            values=names,
        ).pack(
            fill="x",
            padx=18,
        )

        def replace_active(
            active,
            selected,
        ):
            source = os.path.join(
                bin_dir,
                selected.get(),
            )

            if not os.path.isfile(source):
                messagebox.showerror(
                    "Ошибка",
                    f"Файл не найден:\n{source}",
                    parent=win,
                )

                return

            try:
                import shutil

                shutil.copy2(
                    source,
                    active,
                )

            except Exception as exc:
                messagebox.showerror(
                    "Ошибка",
                    str(exc),
                    parent=win,
                )

                return

            messagebox.showinfo(
                "Готово",
                "Активный fake заменён.",
                parent=win,
            )

        row = ctk.CTkFrame(
            win,
            fg_color="transparent",
        )

        row.pack(
            fill="x",
            padx=18,
            pady=18,
        )

        ctk.CTkButton(
            row,
            text="Заменить Discord",
            command=lambda:
                replace_active(
                    active_discord,
                    fake_var1,
                ),
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 4),
        )

        ctk.CTkButton(
            row,
            text="Заменить Game",
            command=lambda:
                replace_active(
                    active_game,
                    fake_var2,
                ),
        ).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(4, 0),
        )

    # ========================================================
    # UPDATES / DIAGNOSTICS / TESTS
    # ========================================================

    def http_get_text(
        self,
        url,
        timeout=15,
    ):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    f"{APP_NAME}/{LOCAL_VERSION}"
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            return response.read().decode(
                "utf-8",
                errors="replace",
            )

    def update_ipset(self):

        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        target = os.path.join(
            version_path,
            "lists",
            "ipset-all.txt",
        )

        try:
            os.makedirs(
                os.path.dirname(target),
                exist_ok=True,
            )

            text = self.http_get_text(
                GITHUB_IPSET_URL
            )

            Path(target).write_text(
                text,
                encoding="utf-8",
            )

            messagebox.showinfo(
                "IPSet",
                "IPSet список успешно обновлён.",
            )

            self.refresh_service_options()

        except Exception as exc:
            messagebox.showerror(
                "Ошибка IPSet",
                str(exc),
            )

    def update_hosts(self):

        temp_dir = os.path.join(
            os.getenv("TEMP")
            or os.path.expanduser("~"),
            "zapret_manager",
        )

        os.makedirs(
            temp_dir,
            exist_ok=True,
        )

        temp = os.path.join(
            temp_dir,
            "hosts.txt",
        )

        try:
            text = self.http_get_text(
                GITHUB_HOSTS_URL
            )

            Path(temp).write_text(
                text,
                encoding="utf-8",
            )

            hosts = os.path.join(
                os.environ.get(
                    "SystemRoot",
                    r"C:\Windows",
                ),
                "System32",
                "drivers",
                "etc",
                "hosts",
            )

            self.show_text_window(
                "Проверка hosts",
                f"Скачанный hosts:\n{temp}\n\n"
                f"Текущий hosts:\n{hosts}\n\n"
                f"Файл открыт в блокноте.",
            )

            subprocess.Popen(
                [
                    "notepad.exe",
                    temp,
                ]
            )

            subprocess.Popen(
                [
                    "explorer.exe",
                    "/select," + hosts,
                ]
            )

        except Exception as exc:
            messagebox.showerror(
                "Ошибка Hosts",
                str(exc),
            )

    def check_updates(self):

        try:
            latest = self.http_get_text(
                GITHUB_VERSION_URL,
                timeout=8,
            ).strip()

            if not latest:
                raise RuntimeError(
                    "Пустой ответ версии"
                )

            if latest == LOCAL_VERSION:

                messagebox.showinfo(
                    "Обновления",
                    f"Установлена последняя версия: "
                    f"{LOCAL_VERSION}",
                )

            else:

                if messagebox.askyesno(
                    "Обновление",
                    f"Доступна новая версия: "
                    f"{latest}\n\n"
                    f"Открыть страницу загрузки?",
                ):
                    os.startfile(
                        GITHUB_DOWNLOAD_URL
                    )

        except Exception as exc:
            messagebox.showwarning(
                "Обновления",
                f"Не удалось проверить обновления:\n{exc}",
            )

    def run_diagnostics(self):

        version_path, _ = (
            self.get_current_paths()
        )

        lines = [
            "=== ZAPRET DIAGNOSTICS ===",
            "",
        ]

        lines.append(
            f"Zapret path: "
            f"{version_path or self.root_dir}"
        )

        # Все эти проверки потенциально тяжёлые,
        # поэтому диагностика целиком выполняется
        # в отдельном потоке.

        def worker():

            diagnostic_lines = list(
                lines
            )

            bfe = ServiceManager.get_service_status(
                "BFE"
            )

            diagnostic_lines.append(
                f"BFE: "
                f"{bfe or 'NOT FOUND'}"
            )

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                ) as key:

                    enabled = winreg.QueryValueEx(
                        key,
                        "ProxyEnable",
                    )[0]

                diagnostic_lines.append(
                    "Proxy: ENABLED"
                    if enabled
                    else "Proxy: disabled"
                )

            except Exception:
                diagnostic_lines.append(
                    "Proxy: unknown"
                )

            try:
                r = run_hidden(
                    [
                        "netsh",
                        "interface",
                        "tcp",
                        "show",
                        "global",
                    ],
                    timeout=10,
                )

                enabled = (
                    "timestamps"
                    in r.stdout.lower()
                    and "enabled"
                    in r.stdout.lower()
                )

                diagnostic_lines.append(
                    "TCP timestamps: "
                    + (
                        "enabled"
                        if enabled
                        else "disabled/unknown"
                    )
                )

            except Exception as exc:
                diagnostic_lines.append(
                    f"TCP timestamps: error ({exc})"
                )

            conflicts = [
                "GoodbyeDPI",
                "discordfix_zapret",
                "winws1",
                "winws2",
                "SmartByte",
                "TracSrvWrapper",
                "EPWD",
            ]

            found = []

            for service in conflicts:

                if ServiceManager.service_exists(
                    service
                ):
                    found.append(
                        service
                    )

            diagnostic_lines.append(
                "Conflicting services: "
                + (
                    ", ".join(found)
                    if found
                    else "none detected"
                )
            )

            try:
                r = run_hidden(
                    [
                        "tasklist",
                        "/FI",
                        "IMAGENAME eq AdguardSvc.exe",
                    ],
                    timeout=10,
                )

                diagnostic_lines.append(
                    "AdGuard: FOUND"
                    if "AdguardSvc.exe"
                    in r.stdout
                    else "AdGuard: not found"
                )

            except Exception:
                diagnostic_lines.append(
                    "AdGuard: unknown"
                )

            if version_path:

                diagnostic_lines.append(
                    "Cyrillic path: "
                    + (
                        "YES"
                        if re.search(
                            r"[А-Яа-яЁё]",
                            version_path,
                        )
                        else "no"
                    )
                )

                diagnostic_lines.append(
                    "OneDrive path: "
                    + (
                        "YES"
                        if "onedrive"
                        in version_path.lower()
                        else "no"
                    )
                )

                sys_dir = os.path.join(
                    version_path,
                    "bin",
                )

                sys_files = (
                    list(
                        Path(sys_dir).glob(
                            "*.sys"
                        )
                    )
                    if os.path.isdir(sys_dir)
                    else []
                )

                diagnostic_lines.append(
                    "WinDivert .sys: "
                    + (
                        "found"
                        if sys_files
                        else "not found"
                    )
                )

            try:
                r = run_hidden(
                    [
                        "sc",
                        "query",
                    ],
                    timeout=15,
                )

                vpn = [
                    line.strip()
                    for line in r.stdout.splitlines()
                    if "VPN" in line.upper()
                ]

                diagnostic_lines.append(
                    "VPN services: "
                    + (
                        "found"
                        if vpn
                        else "none detected"
                    )
                )

            except Exception:
                diagnostic_lines.append(
                    "VPN services: unknown"
                )

            diagnostic_lines.append("")
            diagnostic_lines.append(
                ServiceManager.get_service_diagnostic()
            )

            final_text = "\n".join(
                diagnostic_lines
            )

            if not self.closing:
                self.after(
                    0,
                    self.show_text_window,
                    "Диагностика Zapret",
                    final_text,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="ZapretDiagnostics",
        ).start()

    def show_text_window(
        self,
        title,
        text,
    ):
        win = ctk.CTkToplevel(
            self
        )

        win.title(title)

        win.geometry(
            "720x520"
        )

        win.configure(
            fg_color="#121318"
        )

        box = ctk.CTkTextbox(
            win,
            fg_color="#15161D",
            text_color="#D1D5DB",
            wrap="word",
        )

        box.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=14,
        )

        box.insert(
            "1.0",
            text,
        )

        box.configure(
            state="disabled"
        )

        ctk.CTkButton(
            win,
            text="Закрыть",
            command=win.destroy,
        ).pack(
            fill="x",
            padx=14,
            pady=(0, 14),
        )

    def run_service_tests(self):

        version_path, _ = (
            self.get_current_paths()
        )

        if not version_path:
            return

        ps = os.path.join(
            version_path,
            "utils",
            "test zapret.ps1",
        )

        if not os.path.isfile(ps):
            messagebox.showerror(
                "Тесты",
                f"Файл не найден:\n{ps}",
            )

            return

        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    ps,
                ],
                cwd=version_path,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )

        except Exception as exc:
            messagebox.showerror(
                "Тесты",
                str(exc),
            )

    # ========================================================
    # SETTINGS MENU
    # ========================================================

    def show_settings_menu(self):

        menu = tk.Menu(
            self,
            tearoff=0,
            bg="#1E2029",
            fg="#FFFFFF",
            activebackground="#10B981",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=1,
        )

        menu.add_command(
            label="📁 Сменить корневую папку",
            command=self.change_root_folder,
        )

        menu.add_command(
            label="📂 Открыть текущую папку",
            command=self.open_current_folder,
        )

        menu.add_separator()

        menu.add_command(
            label="🔄 Обновить список версий",
            command=self.refresh_versions,
        )

        menu.add_command(
            label="🔍 Обновить состояние сервиса",
            command=lambda:
                self.refresh_service_ui(
                    include_details=True
                ),
        )

        menu.add_separator()

        menu.add_command(
            label="❌ Выход",
            command=self.quit_app,
        )

        x = self.settings_btn.winfo_rootx()
        y = (
            self.settings_btn.winfo_rooty()
            + self.settings_btn.winfo_height()
            + 4
        )

        try:
            menu.tk_popup(
                x,
                y,
            )

        finally:
            menu.grab_release()

    def change_root_folder(self):

        if self.testing_all:
            return

        folder = filedialog.askdirectory(
            initialdir=(
                self.root_dir
                if os.path.isdir(self.root_dir)
                else os.path.expanduser("~")
            ),
            title="Выберите папку ALL_VERSIONS",
        )

        if folder:
            self.set_root_folder(
                folder
            )

    def refresh_versions(self):

        if self.testing_all:
            return

        self.render_versions_list()

        self.update_window_icon()

        self.status_sub.configure(
            text="Список версий обновлён"
        )

    def open_current_folder(self):

        version_path, _ = (
            self.get_current_paths()
        )

        target = (
            version_path
            if version_path
            and os.path.isdir(version_path)
            else self.root_dir
        )

        if os.path.isdir(target):
            os.startfile(target)

    # ========================================================
    # TRAY
    # ========================================================

    def setup_tray(self):

        if self.tray_icon is not None:
            return

        image = (
            self.icon_image
            if self.icon_image
            else self.create_default_icon()
        )

        self.tray_icon = pystray.Icon(
            "ZapretManager",
            image,
            "Zapret Manager",
            menu=self._build_tray_menu(),
        )

        threading.Thread(
            target=self.tray_icon.run,
            daemon=True,
            name="ZapretTray",
        ).start()

    def _build_tray_menu(self):

        def open_window_action(
            icon,
            menu_item,
        ):
            self.after(
                0,
                self.show_from_tray,
            )

        def start_action(
            icon,
            menu_item,
        ):
            self.after(
                0,
                self.start_process,
            )

        def stop_action(
            icon,
            menu_item,
        ):
            self.after(
                0,
                self.stop_process,
            )

        def service_action(
            icon,
            menu_item,
        ):
            self.after(
                0,
                self.show_service_section,
            )

        def quit_action(
            icon,
            menu_item,
        ):
            self.after(
                0,
                self.quit_app,
            )

        version_items = []

        for version_name in self.versions_data.keys():

            def make_version_action(
                version
            ):
                def action(
                    icon,
                    menu_item,
                ):
                    self.after(
                        0,
                        self.select_version,
                        version,
                    )

                return action

            def make_version_checked(
                version
            ):
                def checked(
                    menu_item
                ):
                    return (
                        self.selected_version.get()
                        == version
                    )

                return checked

            version_items.append(
                item(
                    version_name,
                    make_version_action(
                        version_name
                    ),
                    checked=make_version_checked(
                        version_name
                    ),
                )
            )

        if not version_items:

            def no_versions_action(
                icon,
                menu_item,
            ):
                return None

            version_items.append(
                item(
                    "Нет версий",
                    no_versions_action,
                    enabled=False,
                )
            )

        return pystray.Menu(
            item(
                "Открыть окно",
                open_window_action,
                default=True,
            ),
            item(
                "Запуск",
                start_action,
            ),
            item(
                "Стоп",
                stop_action,
            ),
            item(
                "Сменить версию",
                pystray.Menu(
                    *version_items
                ),
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Показать сервис",
                service_action,
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Выход",
                quit_action,
            ),
        )

    def request_tray_refresh(self):
        """
        Объединяет несколько запросов обновления Tray.

        Например:

            select_version()
              ↓
            update_bat_list()
              ↓
            request_tray_refresh()
              ↓
            request_tray_refresh()

        фактически приведут только к одному обновлению.
        """

        if (
            self.tray_icon is None
            or self.closing
        ):
            return

        if self.tray_refresh_after_id is not None:
            return

        self.tray_refresh_after_id = (
            self.after(
                100,
                self._perform_tray_refresh,
            )
        )

    def _perform_tray_refresh(self):

        self.tray_refresh_after_id = None

        if (
            self.tray_icon is None
            or self.closing
        ):
            return

        try:
            self.tray_icon.menu = (
                self._build_tray_menu()
            )

            if self.icon_image:
                self.tray_icon.icon = (
                    self.icon_image
                )

            self.tray_icon.update_menu()

        except Exception as exc:
            print(
                f"Ошибка обновления трея: {exc}"
            )

    def refresh_tray(self):
        # Оставляем старое имя метода для совместимости.
        self.request_tray_refresh()

    def hide_to_tray(self):

        if self.closing:
            return

        self.withdraw()

    def show_from_tray(self):

        if self.closing:
            return

        self.deiconify()
        self.lift()
        self.focus_force()

    def show_service_section(self):

        self.show_from_tray()

        self.after(
            100,
            lambda:
                self.main_scroll._parent_canvas.yview_moveto(
                    0.62
                ),
        )

    # ========================================================
    # CLEAN EXIT
    # ========================================================

    def quit_app(self):

        if self.closing:
            return

        self.closing = True

        self.shutdown_event.set()
        self.test_cancel_event.set()

        self.testing_all = False

        if self.service_refresh_after_id:

            try:
                self.after_cancel(
                    self.service_refresh_after_id
                )
            except Exception:
                pass

            self.service_refresh_after_id = None

        if self.tray_refresh_after_id:

            try:
                self.after_cancel(
                    self.tray_refresh_after_id
                )
            except Exception:
                pass

            self.tray_refresh_after_id = None

        # Полный выход останавливает standalone процессы.
        # Windows service НЕ останавливается.

        for pid in set(
            self.managed_pids
        ):
            kill_process_by_pid(pid)

        self.managed_pids.clear()

        with self.tray_stop_lock:

            try:
                if self.tray_icon:

                    self.tray_icon.visible = False
                    self.tray_icon.stop()

                    self.tray_icon = None

            except Exception:
                pass

        try:
            self.destroy()

        except Exception:
            pass

        release_mutex()


# ============================================================
