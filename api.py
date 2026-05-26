from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from config import API_BASE_URL, TIMEZONE, WEEKDAY_RU, BELL_SCHEDULE

REQUEST_TIMEOUT = 10.0


@dataclass
class DaySchedule:
    day: datetime
    lessons: list[dict[str, Any]]
    error: str | None = None


async def get_schedule(
    group_id: int,
    date: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    url = f"{API_BASE_URL}/groups/{group_id}/schedules"
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    assert client is not None
    try:
        for attempt in range(2):
            try:
                response = await client.get(url, params={"date": date})
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Unexpected API payload type")
                return payload
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 1:
                    raise
    finally:
        if own_client:
            await client.aclose()

    raise RuntimeError("unreachable")


async def _get_week_schedule_from_monday(monday: datetime, group_id: int) -> list[DaySchedule]:
    """Получить расписание на неделю начиная с указанного понедельника (6 дней пн–сб)"""
    results: list[DaySchedule] = []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for day_offset in range(6):
            day = monday + timedelta(days=day_offset)
            date_str = day.strftime("%d-%m-%Y")
            try:
                data = await get_schedule(group_id, date_str, client=client)
                lessons = data[0].get("lessons", []) if data else []
                if not isinstance(lessons, list):
                    lessons = []
                results.append(DaySchedule(day=day, lessons=lessons))
            except Exception:
                results.append(
                    DaySchedule(
                        day=day,
                        lessons=[],
                        error="Не удалось загрузить расписание",
                    )
                )
    return results


async def get_week_schedule(group_id: int) -> list[DaySchedule]:
    """Расписание на текущую неделю"""
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    monday = today - timedelta(days=today.weekday())
    return await _get_week_schedule_from_monday(monday, group_id)


async def get_next_week_schedule(group_id: int) -> list[DaySchedule]:
    """Расписание на следующую неделю"""
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    next_monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    return await _get_week_schedule_from_monday(next_monday, group_id)


async def check_next_week_available(group_id: int) -> bool:
    """
    Проверяет есть ли расписание на следующий понедельник.
    Если есть хотя бы 1 урок — расписание опубликовано.
    """
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    next_monday = today - timedelta(days=today.weekday()) + timedelta(weeks=1)
    date_str = next_monday.strftime("%d-%m-%Y")
    try:
        data = await get_schedule(group_id, date_str)
        lessons = data[0].get("lessons", []) if data else []
        return isinstance(lessons, list) and len(lessons) > 0
    except Exception:
        return False


def format_day(lessons: list[dict[str, Any]], dt: datetime, error: str | None = None) -> str:
    weekday = WEEKDAY_RU[dt.weekday()]
    date_formatted = dt.strftime("%d.%m.%Y")
    header = f"<b>{escape(weekday.lower())} {date_formatted}:</b>"

    if error:
        return f"{header}\n⚠️ {escape(error)}"
    if not lessons:
        return f"{header}\nПар нет"

    lines = [header]
    sorted_lessons = sorted(lessons, key=lambda item: item.get("order", 0))
    start_times: list[str] = []
    end_times: list[str] = []

    for lesson in sorted_lessons:
        order_val = lesson.get("order", 0)
        order = escape(str(order_val))
        subject = escape(str(lesson.get("title", "Предмет не указан")))
        teacher = escape(str(lesson.get("teacher", "")))
        room = escape(str(lesson.get("cabinet", "")))
        begins = str(lesson.get("startTime", ""))[:5]
        ends = str(lesson.get("endTime", ""))[:5]

        # Если API не вернул время — берём из расписания звонков
        if (not begins or not ends) and isinstance(order_val, int):
            bell = BELL_SCHEDULE.get(order_val)
            if bell:
                begins, ends = bell

        lesson_parts = [f"{order}. {subject}"]
        if teacher:
            lesson_parts.append(teacher)
        if room:
            lesson_parts.append(room)
        if begins and ends:
            lesson_parts.append(f"{escape(begins)}-{escape(ends)}")
            start_times.append(begins)
            end_times.append(ends)
        lines.append(f"<blockquote>{chr(10).join(lesson_parts)}</blockquote>")

    if start_times and end_times:
        lines.append(
            f"Пары начинаются в <u>{escape(min(start_times))}</u>\n"
            f"Пары заканчиваются в <u>{escape(max(end_times))}</u>"
        )

    return "\n\n".join(lines)


async def format_today(group_id: int) -> str:
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    date_str = today.strftime("%d-%m-%Y")
    data = await get_schedule(group_id, date_str)
    lessons = data[0].get("lessons", []) if data else []
    if not isinstance(lessons, list):
        lessons = []
    return format_day(lessons, today)


async def format_tomorrow(group_id: int) -> str:
    tz = ZoneInfo(TIMEZONE)
    tomorrow = datetime.now(tz) + timedelta(days=1)
    date_str = tomorrow.strftime("%d-%m-%Y")
    data = await get_schedule(group_id, date_str)
    lessons = data[0].get("lessons", []) if data else []
    if not isinstance(lessons, list):
        lessons = []
    return format_day(lessons, tomorrow)


async def format_week(group_id: int) -> str:
    week = await get_week_schedule(group_id)
    return "\n——————————\n".join(format_day(item.lessons, item.day, item.error) for item in week)


async def format_next_week(group_id: int) -> str:
    week = await get_next_week_schedule(group_id)
    return "\n——————————\n".join(format_day(item.lessons, item.day, item.error) for item in week)
