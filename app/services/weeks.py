from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.config import get_settings

DAY_NAMES = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]


def today_local() -> date:
    return datetime.now(get_settings().tz).date()


def week_bounds(anchor: date) -> tuple[date, date]:
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def current_week_bounds() -> tuple[date, date]:
    return week_bounds(today_local())


def previous_week_bounds() -> tuple[date, date]:
    start, end = current_week_bounds()
    return start - timedelta(days=7), end - timedelta(days=7)


def week_bounds_for_date(anchor: date) -> tuple[date, date]:
    return week_bounds(anchor)


def day_name(index: int) -> str:
    return DAY_NAMES[index % 7]


def parse_time_text(value: str) -> tuple[int, int] | None:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def next_report_run(now: datetime, weekday: int, time_text: str) -> datetime:
    parsed = parse_time_text(time_text)
    if parsed is None:
        parsed = (9, 0)
    hour, minute = parsed
    tzinfo = now.tzinfo or get_settings().tz
    days_ahead = (weekday - now.weekday()) % 7
    candidate_date = now.date() + timedelta(days=days_ahead)
    candidate = datetime.combine(
        candidate_date, time(hour=hour, minute=minute), tzinfo=tzinfo
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate
