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
    get_resource_path,
)
from .bat_parser import (
    get_bat_files,
    parse_bat_winws_args,
)
from .service_manager import ServiceManager


class ZapretLauncher(tk.Tk):
    """Основное окно приложения ZapretManager"""

    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("800x600")
        self.resizable(True, True)

        self.root_dir = DEFAULT_ROOT_DIR
        self.selected_bat = None
        self.current_version_path = None

        self._load_settings()
        self._build_ui()

    def _load_settings(self):
        """Загрузка настроек из конфигурации"""
        config = load_config()
        self.root_dir = config.get("root_dir", DEFAULT_ROOT_DIR)

    def _build_ui(self):
        """Построение пользовательского интерфейса"""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Верхняя панель с информацией о версии
        info_frame = ttk.LabelFrame(main_frame, text="Информация", padding="5")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(info_frame, text=f"Версия: {LOCAL_VERSION}").pack(anchor=tk.W)
        self.status_label = ttk.Label(info_frame, text="Статус: Ожидание")
        self.status_label.pack(anchor=tk.W)

        # Панель выбора директории
        dir_frame = ttk.LabelFrame(main_frame, text="Директория Zapret", padding="5")
        dir_frame.pack(fill=tk.X, pady=(0, 10))

        self.dir_entry = ttk.Entry(dir_frame, width=50)
        self.dir_entry.insert(0, self.root_dir)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(dir_frame, text="Обзор...", command=self.browse_folder).pack(
            side=tk.LEFT, padx=(5, 0)
        )
        ttk.Button(dir_frame, text="Применить", command=self.apply_folder).pack(
            side=tk.LEFT, padx=(5, 0)
        )

        # Панель выбора BAT файла
        bat_frame = ttk.LabelFrame(main_frame, text="Конфигурация", padding="5")
        bat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.bat_listbox = tk.Listbox(bat_frame)
        bat_scrollbar = ttk.Scrollbar(bat_frame, orient=tk.VERTICAL, command=self.bat_listbox.yview)
        self.bat_listbox.configure(yscrollcommand=bat_scrollbar.set)

        self.bat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.bat_listbox.bind("<<ListboxSelect>>", self.on_bat_select)

        # Панель управления сервисом
        service_frame = ttk.LabelFrame(main_frame, text="Управление сервисом", padding="5")
        service_frame.pack(fill=tk.X, pady=(0, 10))

        self.install_btn = ttk.Button(service_frame, text="Установить сервис", command=self.install_service)
        self.install_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.start_btn = ttk.Button(service_frame, text="Запустить сервис", command=self.start_service)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_btn = ttk.Button(service_frame, text="Остановить сервис", command=self.stop_service)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.delete_btn = ttk.Button(service_frame, text="Удалить сервис", command=self.delete_service)
        self.delete_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Нижняя панель статуса
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X)

        self.ping_label = ttk.Label(bottom_frame, text="Ping: --")
        self.ping_label.pack(side=tk.LEFT)

        self.service_status_label = ttk.Label(bottom_frame, text="Сервис: Не проверено")
        self.service_status_label.pack(side=tk.RIGHT)

        # Обновление списка BAT файлов
        self.refresh_bat_list()

    def browse_folder(self):
        """Открыть диалог выбора папки"""
        folder = filedialog.askdirectory(initialdir=self.root_dir)
        if folder:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, folder)

    def apply_folder(self):
        """Применить выбранную папку"""
        new_dir = self.dir_entry.get().strip()
        if os.path.isdir(new_dir):
            self.root_dir = new_dir
            save_config(self.root_dir)
            self.refresh_bat_list()
            self.status_label.config(text="Статус: Директория применена")
        else:
            messagebox.showerror("Ошибка", f"Директория не найдена:\n{new_dir}")

    def ask_for_folder(self):
        """Запросить выбор папки при запуске"""
        self.browse_folder()
        if self.dir_entry.get():
            self.apply_folder()

    def refresh_bat_list(self):
        """Обновить список BAT файлов"""
        self.bat_listbox.delete(0, tk.END)
        bat_files = get_bat_files(self.root_dir)

        for bat in bat_files:
            self.bat_listbox.insert(tk.END, bat)

        if bat_files:
            self.status_label.config(text=f"Статус: Найдено конфигов: {len(bat_files)}")
        else:
            self.status_label.config(text="Статус: BAT файлы не найдены")

    def on_bat_select(self, event):
        """Обработка выбора BAT файла"""
        selection = self.bat_listbox.curselection()
        if selection:
            index = selection[0]
            self.selected_bat = self.bat_listbox.get(index)
            self.current_version_path = os.path.join(
                self.root_dir,
                os.path.splitext(self.selected_bat)[0],
            )
            self.status_label.config(text=f"Статус: Выбрано: {self.selected_bat}")

    def install_service(self):
        """Установка сервиса"""
        if not self.selected_bat:
            messagebox.showwarning("Предупреждение", "Выберите BAT файл конфигурации")
            return

        bat_path = os.path.join(self.root_dir, self.selected_bat)
        
        if not self.current_version_path:
            self.current_version_path = os.path.join(
                self.root_dir,
                os.path.splitext(self.selected_bat)[0],
            )

        winws_path = os.path.join(self.current_version_path, "winws.exe")

        args, error = parse_bat_winws_args(bat_path, self.current_version_path)

        if error:
            messagebox.showerror("Ошибка", f"Ошибка парсинга BAT:\n{error}")
            return

        success, message = ServiceManager.install_service(
            winws_path,
            args,
            self.selected_bat,
            self.current_version_path,
        )

        if success:
            messagebox.showinfo("Успех", message)
            self.update_service_status()
        else:
            messagebox.showerror("Ошибка", message)

    def start_service(self):
        """Запуск сервиса"""
        success, message = ServiceManager.start_service()

        if success:
            messagebox.showinfo("Успех", message)
            self.update_service_status()
        else:
            messagebox.showerror("Ошибка", message)

    def stop_service(self):
        """Остановка сервиса"""
        success, message = ServiceManager.stop_service()

        if success:
            messagebox.showinfo("Успех", message)
            self.update_service_status()
        else:
            messagebox.showerror("Ошибка", message)

    def delete_service(self):
        """Удаление сервиса"""
        if not messagebox.askyesno("Подтверждение", "Вы уверены, что хотите удалить сервис?"):
            return

        success, message = ServiceManager.delete_service()

        if success:
            messagebox.showinfo("Успех", message)
            self.update_service_status()
        else:
            messagebox.showerror("Ошибка", message)

    def update_service_status(self):
        """Обновление статуса сервиса"""
        status = ServiceManager.get_service_status()

        if status:
            self.service_status_label.config(text=f"Сервис: {status}")
        else:
            self.service_status_label.config(text="Сервис: Не установлен")

        # Проверка ping
        ping = check_tcp_ping("google.com", port=443)
        if ping:
            self.ping_label.config(text=f"Ping: {ping} ms")
        else:
            self.ping_label.config(text="Ping: --")
