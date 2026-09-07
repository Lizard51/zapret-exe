"""
ZapretManager - GUI Module
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .config import (
    APP_NAME,
    LOCAL_VERSION,
    DEFAULT_ROOT_DIR,
)
from .utils import (
    load_config,
    save_config,
    check_tcp_ping,
    is_winws_running,
)
from .service_manager import ServiceManager
from .bat_parser import BatParser


class ZapretLauncher(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("800x600")
        self.resizable(True, True)

        # Load configuration
        config = load_config()
        self.root_dir = config.get("root_dir", DEFAULT_ROOT_DIR)

        # Create main frame
        self.main_frame = ttk.Frame(self, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        # Create widgets
        self._create_menu()
        self._create_widgets()

        # Update status
        self.after(1000, self._update_status)

    def _create_menu(self):
        """Create menu bar."""
        menubar = tk.Menu(self)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Выбрать папку zapret...", command=self.ask_for_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.quit)
        menubar.add_cascade(label="Файл", menu=file_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе", command=self._show_about)
        menubar.add_cascade(label="Помощь", menu=help_menu)

        self.config(menu=menubar)

    def _create_widgets(self):
        """Create main widgets."""
        # Title label
        title_label = ttk.Label(
            self.main_frame,
            text=f"{APP_NAME} v{LOCAL_VERSION}",
            font=("Arial", 16, "bold"),
        )
        title_label.grid(row=0, column=0, pady=(0, 20))

        # Root directory frame
        dir_frame = ttk.LabelFrame(self.main_frame, text="Папка zapret", padding="10")
        dir_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        dir_frame.columnconfigure(1, weight=1)

        ttk.Label(dir_frame, text="Путь:").grid(row=0, column=0, sticky=tk.W)
        self.dir_var = tk.StringVar(value=self.root_dir)
        dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var, state="readonly")
        dir_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5))

        ttk.Button(dir_frame, text="Обзор...", command=self.ask_for_folder).grid(
            row=0, column=2
        )

        # Status frame
        status_frame = ttk.LabelFrame(self.main_frame, text="Статус", padding="10")
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        status_frame.columnconfigure(1, weight=1)

        ttk.Label(status_frame, text="winws:").grid(row=0, column=0, sticky=tk.W)
        self.winws_status_var = tk.StringVar(value="Неизвестно")
        ttk.Label(status_frame, textvariable=self.winws_status_var).grid(
            row=0, column=1, sticky=tk.W, padx=(5, 0)
        )

        ttk.Label(status_frame, text="Сервис:").grid(row=1, column=0, sticky=tk.W)
        self.service_status_var = tk.StringVar(value="Неизвестно")
        ttk.Label(status_frame, textvariable=self.service_status_var).grid(
            row=1, column=1, sticky=tk.W, padx=(5, 0)
        )

        # Control buttons frame
        control_frame = ttk.Frame(self.main_frame)
        control_frame.grid(row=3, column=0, pady=10)

        ttk.Button(control_frame, text="Запустить", command=self._start_winws).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(control_frame, text="Остановить", command=self._stop_winws).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(
            control_frame, text="Установить сервис", command=self._install_service
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            control_frame, text="Удалить сервис", command=self._delete_service
        ).pack(side=tk.LEFT, padx=5)

        # Log/text area
        log_frame = ttk.LabelFrame(self.main_frame, text="Лог", padding="10")
        log_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, width=50, state="disabled")
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _update_status(self):
        """Update status information."""
        # Check winws status
        if is_winws_running():
            self.winws_status_var.set("Запущен")
        else:
            self.winws_status_var.set("Остановлен")

        # Check service status
        if ServiceManager.service_exists():
            status = ServiceManager.get_service_status()
            if status:
                self.service_status_var.set(status)
            else:
                self.service_status_var.set("Неизвестно")
        else:
            self.service_status_var.set("Не установлен")

        # Schedule next update
        self.after(2000, self._update_status)

    def ask_for_folder(self):
        """Open folder selection dialog."""
        folder = filedialog.askdirectory(
            initialdir=self.root_dir,
            title="Выберите папку с zapret"
        )
        if folder:
            self.root_dir = folder
            self.dir_var.set(folder)
            save_config(folder)
            self._log(f"Папка изменена на: {folder}")

    def _start_winws(self):
        """Start winws process."""
        self._log("Запуск winws...")
        # Implementation would go here
        messagebox.showinfo("Инфо", "Функция запуска будет реализована")

    def _stop_winws(self):
        """Stop winws process."""
        self._log("Остановка winws...")
        # Implementation would go here
        messagebox.showinfo("Инфо", "Функция остановки будет реализована")

    def _install_service(self):
        """Install Windows service."""
        self._log("Установка сервиса...")
        # Implementation would go here
        messagebox.showinfo("Инфо", "Функция установки сервиса будет реализована")

    def _delete_service(self):
        """Delete Windows service."""
        self._log("Удаление сервиса...")
        # Implementation would go here
        messagebox.showinfo("Инфо", "Функция удаления сервиса будет реализована")

    def _show_about(self):
        """Show about dialog."""
        messagebox.showinfo(
            "О программе",
            f"{APP_NAME}\nВерсия: {LOCAL_VERSION}\n\n"
            "Менеджер для управления zapret DPI bypass."
        )

    def _log(self, message):
        """Add message to log."""
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
