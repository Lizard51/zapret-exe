"""
ZapretManager - Configuration module
"""

import os

APP_NAME = "ZapretManager"
MUTEX_NAME = "ZapretManager_Mutex"

DEFAULT_ROOT_DIR = r"D:\Games\zapret\ALL_VERSIONS"

APPDATA_DIR = os.path.join(
    os.getenv("APPDATA") or os.path.expanduser("~"),
    APP_NAME,
)
CONFIG_FILE = os.path.join(APPDATA_DIR, "zapret_config.json")

HIDDEN_WINDOW_FLAG = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0

WINWS_START_TIMEOUT = 8.0
WINWS_POLL_INTERVAL = 0.25
PROCESS_STOP_TIMEOUT = 5.0

PING_ATTEMPTS = 3
PING_INTERVAL = 0.2
PING_TIMEOUT = 2.0

SERVICE_POLL_INTERVAL = 0.5
SERVICE_START_TIMEOUT = 20.0
SERVICE_STOP_TIMEOUT = 15.0

SERVICE_NAME = "zapret"
SERVICE_DISPLAY_NAME = "zapret"
SERVICE_DESCRIPTION = "Zapret DPI bypass software"
SERVICE_STRATEGY_VALUE = "zapret-discord-youtube"

LOCAL_VERSION = "1.10.2"

GITHUB_VERSION_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
    "main/.service/version.txt"
)

GITHUB_DOWNLOAD_URL = (
    "https://github.com/Flowseal/zapret-discord-youtube/releases/latest"
)

GITHUB_IPSET_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
    "refs/heads/main/.service/ipset-service.txt"
)

GITHUB_HOSTS_URL = (
    "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
    "refs/heads/main/.service/hosts"
)

mutex_handle = None
mutex_released = False
