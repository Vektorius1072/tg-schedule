import requests
from datetime import datetime, timedelta
from config import API_BASE_URL, WEEKDAY_RU


def get_schedule(group_id: int, date: str) -> list[dict]:
    """Получить расписание для группы на дату (формат: YYYY-MM-DD)"""
    url = f"{API_BASE_URL}/groups/{group_id}/schedules"
    resp = requests.get(url, params={"date": date}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_week_schedule(group_id: int) -> list[dict]:
    """Получить расписание на текущую неделю (пн–сб)"""
    today = datetime.now()
    # Начало текущей недели (понедельник)
    monday = today - timedelta(days=today.weekday())
    results = []
    for i in range(6):  # пн–сб
        day = monday + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        try:
            data = get_schedule(group_id, date_str)
            results.append((day, data))
        except Exception:
            results.append((day, []))
    return results


def format_day(lessons: list[dict], dt: datetime) -> str:
    """Форматировать один день расписания"""
    weekday = WEEKDAY_RU[dt.weekday()]
    date_formatted = dt.strftime("%d.%m.%Y")

    if not lessons:
        return f"📅 *{weekday}, {date_formatted}*\n😴 Пар нет\n"

    lines = [f"📅 *{weekday}, {date_formatted}*"]
    sorted_lessons = sorted(lessons, key=lambda x: x.get("order", 0))

    for lesson in sorted_lessons:
        order   = lesson.get("order", "?")
        subject = lesson.get("title", "Предмет не указан")
        teacher = lesson.get("teacher", "")
        room    = lesson.get("cabinet", "")
        begins  = lesson.get("startTime", "")[:5]
        ends    = lesson.get("endTime", "")[:5]

        time_str = f"`{begins}–{ends}`" if begins and ends else ""
        line = f"*{order}.* {subject}"
        if time_str:
            line += f"  {time_str}"
        if teacher:
            line += f"\n    👤 {teacher}"
        if room:
            line += f"  🚪 {room}"
        lines.append(line)

    return "\n".join(lines)


def format_tomorrow(group_id: int) -> str:
    """Форматировать расписание на завтра"""
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    data = get_schedule(group_id, date_str)
    lessons = data[0].get("lessons", []) if data else []
    return format_day(lessons, tomorrow)


def format_week(group_id: int) -> str:
    """Форматировать расписание на неделю"""
    week = get_week_schedule(group_id)
    parts = []
    for dt, data in week:
        lessons = data[0].get("lessons", []) if data else []
        parts.append(format_day(lessons, dt))
    return "\n\n".join(parts)
