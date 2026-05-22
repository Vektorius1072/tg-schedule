import json
import os


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _get_int_env(name: str, default: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        if default is None:
            raise RuntimeError(f"Environment variable {name} is required")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


def _get_str_env(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if value == "":
        return default
    return value


def _get_groups() -> dict[str, int]:
    raw = os.getenv("GROUPS_JSON")
    if raw is None:
        return {"IS-25-3S": 113}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GROUPS_JSON must be valid JSON object") from exc

    if not isinstance(data, dict) or not data:
        raise RuntimeError("GROUPS_JSON must be a non-empty JSON object")

    normalized: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError("Each GROUPS_JSON key must be non-empty string")
        if not isinstance(value, int):
            raise RuntimeError("Each GROUPS_JSON value must be integer group id")
        normalized[key] = value

    return normalized


BOT_TOKEN = _get_required_env("BOT_TOKEN")
GROUP_CHAT_ID = _get_int_env("GROUP_CHAT_ID")

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "https://api.thisishyum.ru/schedule_api/tyumen",
).rstrip("/")

GROUPS = _get_groups()

DEFAULT_GROUP_ID = _get_int_env("DEFAULT_GROUP_ID", next(iter(GROUPS.values())))
DEFAULT_GROUP_NAME = os.getenv("DEFAULT_GROUP_NAME")
if DEFAULT_GROUP_NAME is None:
    DEFAULT_GROUP_NAME = next((name for name, gid in GROUPS.items() if gid == DEFAULT_GROUP_ID), None)
if DEFAULT_GROUP_NAME is None:
    raise RuntimeError("DEFAULT_GROUP_ID must exist in GROUPS_JSON")

SEND_HOUR = _get_int_env("SEND_HOUR", 20)
SEND_MINUTE = _get_int_env("SEND_MINUTE", 0)
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
APP_URL = _get_str_env("APP_URL")
PORT = _get_int_env("PORT", 8080)
SELF_PING_INTERVAL_SECONDS = _get_int_env("SELF_PING_INTERVAL_SECONDS", 600)
SELF_PING_START_DELAY_SECONDS = _get_int_env("SELF_PING_START_DELAY_SECONDS", 60)

if not (0 <= SEND_HOUR <= 23):
    raise RuntimeError("SEND_HOUR must be between 0 and 23")
if not (0 <= SEND_MINUTE <= 59):
    raise RuntimeError("SEND_MINUTE must be between 0 and 59")
if PORT <= 0:
    raise RuntimeError("PORT must be positive")
if SELF_PING_INTERVAL_SECONDS < 60:
    raise RuntimeError("SELF_PING_INTERVAL_SECONDS must be at least 60")
if SELF_PING_START_DELAY_SECONDS < 0:
    raise RuntimeError("SELF_PING_START_DELAY_SECONDS must be >= 0")

WEEKDAY_RU = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]
