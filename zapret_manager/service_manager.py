"""
ZapretManager - Windows Service Manager
"""

import os
import re
import time
import winreg

from .config import (
    SERVICE_NAME,
    SERVICE_DISPLAY_NAME,
    SERVICE_DESCRIPTION,
    SERVICE_STRATEGY_VALUE,
    SERVICE_POLL_INTERVAL,
    SERVICE_START_TIMEOUT,
    SERVICE_STOP_TIMEOUT,
    PROCESS_STOP_TIMEOUT,
)
from .utils import (
    run_hidden,
    is_admin,
    get_winws_pids,
    kill_winws,
    wait_until_no_winws,
    normalize_bat_name,
    is_winws_running,
)


class ServiceManager:

    @staticmethod
    def service_exists(service_name=SERVICE_NAME):
        try:
            result = run_hidden(
                [
                    "sc",
                    "query",
                    service_name,
                ],
                timeout=10,
            )

            if (
                result.returncode == 1060
                or "1060" in (
                    result.stdout
                    + result.stderr
                )
            ):
                return False

            return result.returncode == 0

        except Exception:
            return False

    @staticmethod
    def query_service(service_name=SERVICE_NAME):
        try:
            result = run_hidden(
                [
                    "sc",
                    "query",
                    service_name,
                ],
                timeout=10,
            )

            if result.returncode != 0:
                return None

            info = {
                "state": "UNKNOWN",
                "state_code": None,
                "win32_exit_code": None,
                "service_exit_code": None,
                "checkpoint": None,
                "wait_hint": None,
            }

            for raw in result.stdout.splitlines():
                line = raw.strip()
                upper = line.upper()

                if upper.startswith("STATE"):
                    m = re.search(
                        r":\s*(\d+)\s+([A-Z_]+)",
                        line,
                        re.I,
                    )

                    if m:
                        info["state_code"] = int(m.group(1))
                        info["state"] = m.group(2).upper()

                elif "WIN32_EXIT_CODE" in upper:
                    m = re.search(
                        r":\s*(\d+)",
                        line,
                    )

                    if m:
                        info["win32_exit_code"] = int(m.group(1))

                elif "SERVICE_EXIT_CODE" in upper:
                    m = re.search(
                        r":\s*(\d+)",
                        line,
                    )

                    if m:
                        info["service_exit_code"] = int(m.group(1))

                elif "CHECKPOINT" in upper:
                    m = re.search(
                        r":\s*(\d+)",
                        line,
                    )

                    if m:
                        info["checkpoint"] = int(m.group(1))

                elif "WAIT_HINT" in upper:
                    m = re.search(
                        r":\s*(\d+)",
                        line,
                    )

                    if m:
                        info["wait_hint"] = int(m.group(1))

            return info

        except Exception:
            return None

    @staticmethod
    def get_service_status(service_name=SERVICE_NAME):
        data = ServiceManager.query_service(service_name)

        return data["state"] if data else None

    @staticmethod
    def get_service_config(service_name=SERVICE_NAME):
        try:
            result = run_hidden(
                [
                    "sc",
                    "qc",
                    service_name,
                ],
                timeout=10,
            )

            if result.returncode != 0:
                return {
                    "raw": result.stdout or result.stderr
                }

            data = {
                "raw": result.stdout
            }

            for raw in result.stdout.splitlines():
                stripped = raw.strip()

                if "BINARY_PATH_NAME" in stripped.upper():
                    data["binary_path"] = (
                        stripped.split(":", 1)[1].strip()
                        if ":" in stripped
                        else ""
                    )

                elif "START_TYPE" in stripped.upper():
                    data["start_type"] = stripped

                elif "DISPLAY_NAME" in stripped.upper():
                    data["display_name"] = (
                        stripped.split(":", 1)[1].strip()
                        if ":" in stripped
                        else ""
                    )

            return data

        except Exception as exc:
            return {
                "raw": str(exc)
            }

    @staticmethod
    def get_service_strategy(service_name=SERVICE_NAME):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{service_name}",
                0,
                winreg.KEY_READ,
            ) as key:

                value, _ = winreg.QueryValueEx(
                    key,
                    SERVICE_STRATEGY_VALUE,
                )

                return str(value)

        except (FileNotFoundError, OSError):
            return None

    @staticmethod
    def set_service_strategy(
        strategy,
        service_name=SERVICE_NAME,
    ):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{service_name}",
                0,
                winreg.KEY_WRITE,
            ) as key:

                winreg.SetValueEx(
                    key,
                    SERVICE_STRATEGY_VALUE,
                    0,
                    winreg.REG_SZ,
                    str(strategy),
                )

            return True

        except OSError:
            return False

    @staticmethod
    def _sc_error(result):
        text = "\n".join(
            x
            for x in [
                result.stdout.strip(),
                result.stderr.strip(),
            ]
            if x
        )

        return (
            text
            or f"SC завершился с кодом {result.returncode}"
        )

    @staticmethod
    def install_service(
        bin_path,
        args,
        strategy_name,
        version_path,
    ):
        if not is_admin():
            return (
                False,
                "Для установки сервиса нужны права администратора.",
            )

        if not os.path.isfile(bin_path):
            return (
                False,
                f"winws.exe не найден:\n{bin_path}",
            )

        if ServiceManager.service_exists():
            ServiceManager.stop_service(
                wait_timeout=SERVICE_STOP_TIMEOUT
            )

            delete_ok, delete_msg = (
                ServiceManager.delete_service()
            )

            if (
                not delete_ok
                and ServiceManager.service_exists()
            ):
                return (
                    False,
                    f"Не удалось удалить старый сервис:\n{delete_msg}",
                )

        old_pids = get_winws_pids()

        if old_pids:
            kill_winws()
            wait_until_no_winws(
                PROCESS_STOP_TIMEOUT
            )

        binary_quoted = (
            f'"{os.path.abspath(bin_path)}"'
        )

        bin_path_value = (
            binary_quoted
            + (f" {args}" if args else "")
        )

        try:
            create_result = run_hidden(
                [
                    "sc",
                    "create",
                    SERVICE_NAME,
                    "binPath=",
                    bin_path_value,
                    "DisplayName=",
                    SERVICE_DISPLAY_NAME,
                    "start=",
                    "auto",
                ],
                timeout=30,
            )

            if create_result.returncode != 0:
                return (
                    False,
                    "Ошибка создания сервиса:\n"
                    + ServiceManager._sc_error(
                        create_result
                    ),
                )

            desc_result = run_hidden(
                [
                    "sc",
                    "description",
                    SERVICE_NAME,
                    SERVICE_DESCRIPTION,
                ],
                timeout=10,
            )

            if desc_result.returncode != 0:
                return (
                    False,
                    "Сервис создан, но не удалось установить описание.\n\n"
                    + ServiceManager._sc_error(
                        desc_result
                    ),
                )

            if not ServiceManager.set_service_strategy(
                normalize_bat_name(strategy_name)
            ):
                return (
                    False,
                    "Сервис создан, но не удалось записать выбранную стратегию в реестр.",
                )

            ok, start_msg = ServiceManager.start_service()

            if not ok:
                diagnostic = (
                    ServiceManager.get_service_diagnostic()
                )

                return (
                    False,
                    start_msg
                    + "\n\n"
                    + diagnostic,
                )

            return (
                True,
                f"Сервис успешно установлен и запущен.\n\n"
                f"Стратегия: {normalize_bat_name(strategy_name)}\n"
                f"Путь: {bin_path}\n\n"
                f"Аргументы:\n{args or '(нет)'}",
            )

        except Exception as exc:
            return (
                False,
                f"Ошибка установки сервиса:\n{exc}",
            )

    @staticmethod
    def start_service(service_name=SERVICE_NAME):
        if not ServiceManager.service_exists(service_name):
            return (
                False,
                "Сервис zapret не установлен.",
            )

        current = ServiceManager.get_service_status(
            service_name
        )

        if current == "RUNNING":
            return (
                True,
                "Сервис уже запущен.",
            )

        try:
            result = run_hidden(
                [
                    "sc",
                    "start",
                    service_name,
                ],
                timeout=30,
            )

            if result.returncode != 0:
                current = (
                    ServiceManager.get_service_status(
                        service_name
                    )
                )

                if current != "RUNNING":
                    return (
                        False,
                        "Ошибка запуска сервиса:\n"
                        + ServiceManager._sc_error(
                            result
                        ),
                    )

        except Exception as exc:
            return (
                False,
                f"Ошибка запуска сервиса:\n{exc}",
            )

        end = (
            time.monotonic()
            + SERVICE_START_TIMEOUT
        )

        while time.monotonic() < end:
            info = ServiceManager.query_service(
                service_name
            )

            if not info:
                return (
                    False,
                    "Сервис исчез во время запуска.",
                )

            state = info["state"]

            if state == "RUNNING":
                return (
                    True,
                    "Сервис успешно запущен.",
                )

            if state == "STOPPED":
                return (
                    False,
                    ServiceManager._format_service_failure(
                        info
                    ),
                )

            time.sleep(
                SERVICE_POLL_INTERVAL
            )

        info = ServiceManager.query_service(
            service_name
        )

        if info and info.get("state") == "RUNNING":
            return (
                True,
                "Сервис успешно запущен.",
            )

        if info:
            return (
                False,
                "Сервис не перешёл в состояние RUNNING.\n\n"
                + ServiceManager._format_service_failure(
                    info
                ),
            )

        return (
            False,
            "Сервис не перешёл в состояние RUNNING: "
            "не удалось получить его состояние.",
        )

    @staticmethod
    def stop_service(
        service_name=SERVICE_NAME,
        wait_timeout=SERVICE_STOP_TIMEOUT,
    ):
        if not ServiceManager.service_exists(
            service_name
        ):
            return (
                True,
                "Сервис не установлен.",
            )

        current = ServiceManager.get_service_status(
            service_name
        )

        if current == "STOPPED":
            return (
                True,
                "Сервис уже остановлен.",
            )

        try:
            result = run_hidden(
                [
                    "sc",
                    "stop",
                    service_name,
                ],
                timeout=30,
            )

            if (
                result.returncode != 0
                and ServiceManager.get_service_status(
                    service_name
                )
                not in (
                    "STOP_PENDING",
                    "STOPPED",
                )
            ):
                return (
                    False,
                    "Ошибка остановки сервиса:\n"
                    + ServiceManager._sc_error(
                        result
                    ),
                )

        except Exception as exc:
            return (
                False,
                f"Ошибка остановки сервиса:\n{exc}",
            )

        end = (
            time.monotonic()
            + wait_timeout
        )

        while time.monotonic() < end:
            state = ServiceManager.get_service_status(
                service_name
            )

            if state == "STOPPED":
                return (
                    True,
                    "Сервис успешно остановлен.",
                )

            time.sleep(
                SERVICE_POLL_INTERVAL
            )

        state = ServiceManager.get_service_status(
            service_name
        )

        if state == "STOPPED":
            return (
                True,
                "Сервис успешно остановлен.",
            )

        return (
            False,
            f"Сервис не перешёл в STOPPED "
            f"(текущий статус: {state}).",
        )

    @staticmethod
    def delete_service(
        service_name=SERVICE_NAME,
    ):
        if not ServiceManager.service_exists(
            service_name
        ):
            return (
                True,
                "Сервис не установлен.",
            )

        stop_ok, stop_msg = (
            ServiceManager.stop_service(
                service_name
            )
        )

        if not stop_ok:
            if ServiceManager.service_exists(
                service_name
            ):
                return False, stop_msg

        try:
            result = run_hidden(
                [
                    "sc",
                    "delete",
                    service_name,
                ],
                timeout=30,
            )

            if (
                result.returncode != 0
                and ServiceManager.service_exists(
                    service_name
                )
            ):
                return (
                    False,
                    "Ошибка удаления сервиса:\n"
                    + ServiceManager._sc_error(
                        result
                    ),
                )

        except Exception as exc:
            return (
                False,
                f"Ошибка удаления сервиса:\n{exc}",
            )

        end = time.monotonic() + 5

        while (
            time.monotonic() < end
            and ServiceManager.service_exists(
                service_name
            )
        ):
            time.sleep(0.25)

        if ServiceManager.service_exists(
            service_name
        ):
            return (
                False,
                "Сервис помечен на удаление, "
                "но ещё присутствует в SCM.",
            )

        return (
            True,
            "Сервис успешно удалён.",
        )

    @staticmethod
    def restart_service(
        service_name=SERVICE_NAME,
    ):
        ok, msg = ServiceManager.stop_service(
            service_name
        )

        if not ok:
            return False, msg

        return ServiceManager.start_service(
            service_name
        )

    @staticmethod
    def is_windivert_installed():
        return (
            ServiceManager.service_exists("WinDivert")
            or ServiceManager.service_exists("WinDivert14")
        )

    @staticmethod
    def get_service_diagnostic(
        service_name=SERVICE_NAME,
    ):
        lines = []

        exists = ServiceManager.service_exists(
            service_name
        )

        lines.append(
            f"Сервис: "
            f"{'установлен' if exists else 'не установлен'}"
        )

        if exists:
            info = ServiceManager.query_service(
                service_name
            )

            config = ServiceManager.get_service_config(
                service_name
            )

            strategy = ServiceManager.get_service_strategy(
                service_name
            )

            lines.append(
                f"Статус: "
                f"{info.get('state') if info else 'UNKNOWN'}"
            )

            if info:
                lines.append(
                    f"Win32 exit code: "
                    f"{info.get('win32_exit_code')}"
                )

                lines.append(
                    f"Service exit code: "
                    f"{info.get('service_exit_code')}"
                )

                lines.append(
                    f"Checkpoint: "
                    f"{info.get('checkpoint')}"
                )

                lines.append(
                    f"Wait hint: "
                    f"{info.get('wait_hint')}"
                )

            lines.append(
                f"Стратегия: "
                f"{strategy or 'не записана'}"
            )

            if config.get("binary_path"):
                lines.append(
                    f"Binary path: "
                    f"{config['binary_path']}"
                )

        lines.append(
            f"winws.exe: "
            f"{'работает' if is_winws_running() else 'не запущен'}"
        )

        lines.append(
            f"WinDivert: "
            f"{'найден' if ServiceManager.is_windivert_installed() else 'не найден'}"
        )

        return "\n".join(lines)

    @staticmethod
    def _format_service_failure(info):
        state = info.get("state") or "UNKNOWN"

        return (
            f"Состояние: {state}\n"
            f"Win32 exit code: "
            f"{info.get('win32_exit_code')}\n"
            f"Service exit code: "
            f"{info.get('service_exit_code')}\n"
            f"Checkpoint: "
            f"{info.get('checkpoint')}\n"
            f"Wait hint: "
            f"{info.get('wait_hint')}"
        )
