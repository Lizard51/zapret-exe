"""
ZapretManager - A GUI application for managing Zapret DPI bypass configurations.
"""

__version__ = "1.10.2"
__author__ = "Flowseal"

from .config import (
    APP_NAME,
    LOCAL_VERSION,
)
from .gui import ZapretLauncher
from .__main__ import main

__all__ = [
    "APP_NAME",
    "LOCAL_VERSION",
    "ZapretLauncher",
    "main",
]
