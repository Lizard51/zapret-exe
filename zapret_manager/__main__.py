"""
ZapretManager - Main Entry Point
"""

import ctypes
import os
import tkinter as tk
from tkinter import messagebox

from .config import APP_NAME
from .utils import (
    is_admin,
    launch_as_admin,
    create_mutex,
    release_mutex,
    activate_existing_window,
)
from .gui import ZapretLauncher


def main():
    if not is_admin():
        if launch_as_admin():
            return

        root = tk.Tk()
        root.withdraw()

        messagebox.showerror(
            "Ошибка",
            "Не удалось получить права администратора.",
        )

        root.destroy()

        return

    created, handle = create_mutex()

    if not created:
        activate_existing_window()

        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)

        return

    app = ZapretLauncher()

    if not os.path.isdir(app.root_dir):
        app.after(200, app.ask_for_folder)

    try:
        app.mainloop()
    finally:
        release_mutex()


if __name__ == "__main__":
    main()
