"""
ZapretManager - BAT file parsing utilities
"""

import os
import re
import shlex

from .config import DEFAULT_ROOT_DIR


def _strip_batch_comment(text):
    text = text.strip()

    if "::" in text:
        text = text.split("::", 1)[0].rstrip()

    match = re.search(
        r"\brem\b",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        text = text[:match.start()].rstrip()

    return text


def _find_winws_invocation(lines):
    candidates = []

    for raw in lines:
        line = _strip_batch_comment(raw)

        if not line or line.lstrip().startswith("::"):
            continue

        if "winws.exe" not in line.lower():
            continue

        candidates.append(line)

    if not candidates:
        return None

    candidates.sort(
        key=lambda s: (
            "start " in s.lower(),
            len(s),
        )
    )

    return candidates[0]


def _extract_command_after_exe(line):
    match = re.search(
        r"winws\.exe\"?",
        line,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return line[match.end():].strip()


def windows_tokenize(text):
    try:
        lexer = shlex.shlex(
            text,
            posix=False,
        )

        lexer.whitespace_split = True
        lexer.commenters = ""

        return list(lexer)

    except Exception:
        return re.findall(
            r'"(?:[^"\\]|\\.)*"|[^\\s]+',
            text,
        )


def _unquote(token):
    if len(token) >= 2 and token[0] == token[-1] == '"':
        return token[1:-1]

    return token


def _expand_bat_path_token(token, version_path):
    raw = _unquote(token)
    raw = raw.strip()

    raw = raw.replace(
        "%~dp0",
        version_path + os.sep,
    )

    raw = raw.replace(
        "%~dP0",
        version_path + os.sep,
    )

    raw = raw.replace(
        "%cd%",
        version_path,
    )

    raw = raw.replace(
        "%CD%",
        version_path,
    )

    if raw.startswith("@"):
        path_value = raw[1:]

        if path_value and not os.path.isabs(path_value):
            raw = "@" + os.path.join(
                version_path,
                path_value,
            )

        return raw

    lower = raw.lower()

    looks_like_path = (
        raw.startswith(".")
        or "\\" in raw
        or "/" in raw
        or lower.endswith(
            (
                ".txt",
                ".bin",
                ".dat",
                ".lst",
            )
        )
    )

    if looks_like_path and not os.path.isabs(raw):
        raw = os.path.normpath(
            os.path.join(
                version_path,
                raw,
            )
        )

    return raw


def parse_bat_winws_args(bat_path, version_path):
    try:
        with open(
            bat_path,
            "r",
            encoding="utf-8-sig",
            errors="ignore",
        ) as f:
            lines = f.read().splitlines()

    except Exception as exc:
        return None, f"Не удалось прочитать BAT: {exc}"

    line = _find_winws_invocation(lines)

    if not line:
        return None, "В BAT не найдена команда с winws.exe"

    args_text = _extract_command_after_exe(line)

    if args_text is None:
        return None, "Не удалось извлечь аргументы winws.exe"

    tokens = windows_tokenize(args_text)

    if not tokens:
        return "", None

    cleaned = []

    for token in tokens:
        if token in ("^", "^^"):
            continue

        token = token.replace("^!", "!")

        cleaned.append(token)

    args = []

    args_with_value = {
        "sni",
        "host",
        "altorder",
    }

    i = 0

    while i < len(cleaned):
        token = _unquote(cleaned[i])

        if not token:
            i += 1
            continue

        if token.startswith("%") and token.endswith("%"):
            token = token.replace(
                "%~dp0",
                version_path + os.sep,
            )

        if token.startswith("--"):
            key = token[2:].lower()

            args.append(token)

            if (
                key in args_with_value
                and i + 1 < len(cleaned)
            ):
                i += 1

                value = _expand_bat_path_token(
                    cleaned[i],
                    version_path,
                )

                args.append(value)

        else:
            args.append(
                _expand_bat_path_token(
                    token,
                    version_path,
                )
            )

        i += 1

    return build_service_arguments(args), None


def build_service_arguments(args):
    parts = []

    for arg in args:
        arg = str(arg)

        if not arg:
            continue

        if (
            any(ch.isspace() for ch in arg)
            or "&" in arg
            or "(" in arg
            or ")" in arg
        ):
            escaped = arg.replace(
                '"',
                '\\"',
            )

            parts.append(
                f'"{escaped}"'
            )

        else:
            parts.append(arg)

    return " ".join(parts)


def get_bat_files(version_path):
    if not os.path.isdir(version_path):
        return []

    try:
        result = []

        for name in os.listdir(version_path):
            p = os.path.join(
                version_path,
                name,
            )

            if (
                os.path.isfile(p)
                and name.lower().endswith(".bat")
                and not name.lower().startswith("service")
            ):
                result.append(name)

        return sorted(
            result,
            key=str.lower,
        )

    except Exception:
        return []
