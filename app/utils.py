from __future__ import annotations

import html
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.models import TicketKind, TripStatus

_DURATION_HOURS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hora|horas)\b", re.IGNORECASE
)
_DURATION_MINUTES = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:m|min|mins|minuto|minutos)\b", re.IGNORECASE
)

FIELD_LABELS = {
    "origin": "Origen",
    "destination": "Destino",
    "distance": "Millas",
    "duration": "Tiempo",
    "weight": "Peso",
    "percentage": "% Conductor",
    "payment": "Pago de la carga",
    "date": "Fecha",
    "status": "Estado",
    "notes": "Notas",
    "truck": "Camión",
    "driver": "Conductor",
}


def parse_decimal(raw: str) -> Decimal | None:
    text = raw.strip()
    text = text.replace("$", "").replace("%", "").replace(" ", "").replace("_", "")
    if not text:
        return None
    try:
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return value


def parse_duration_minutes(raw: str) -> int | None:
    text = raw.strip().lower()
    if not text:
        return None

    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            return None
        hours = parse_decimal(parts[0])
        minutes = parse_decimal(parts[1])
        if hours is None or minutes is None:
            return None
        if hours < 0 or minutes < 0 or minutes >= 60:
            return None
        total = int(round(hours * 60 + minutes))
        return total if total > 0 else None

    hours_match = _DURATION_HOURS.search(text)
    minutes_match = _DURATION_MINUTES.search(text)
    if hours_match and minutes_match:
        hours = parse_decimal(hours_match.group(1))
        minutes = parse_decimal(minutes_match.group(1))
        if hours is None or minutes is None:
            return None
        total = int(round(hours * 60 + minutes))
        return total if total > 0 else None
    if hours_match:
        hours = parse_decimal(hours_match.group(1))
        if hours is None:
            return None
        total = int(round(hours * 60))
        return total if total > 0 else None
    if minutes_match:
        minutes = parse_decimal(minutes_match.group(1))
        if minutes is None:
            return None
        total = int(round(minutes))
        return total if total > 0 else None

    hours = parse_decimal(text)
    if hours is None:
        return None
    total = int(round(hours * 60))
    return total if total > 0 else None


def parse_date_text(raw: str) -> date | None:
    text = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_number(value: Decimal | float | int | None, places: int = 2) -> str:
    if value is None:
        return "0"
    quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-places))
    return f"{quantized:,.{places}f}"


def format_money(value: Decimal | float | int | None, currency: str = "$") -> str:
    return f"{currency}{format_number(value, 2)}"


def format_duration(total_minutes: int | None) -> str:
    if not total_minutes or total_minutes <= 0:
        return "0m"
    hours, minutes = divmod(int(total_minutes), 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def format_week_range(start: date, end: date) -> str:
    return f"{format_date(start)} al {format_date(end)}"


def status_label(status: TripStatus) -> str:
    return "Finalizado" if status == TripStatus.finished else "En curso"


def kind_label(kind: TicketKind) -> str:
    labels = {
        TicketKind.fuel: "Gasolina",
        TicketKind.maintenance: "Mantenimiento",
        TicketKind.other: "Otro",
    }
    return labels[kind]


def safe_escape(value: str | None) -> str:
    return html.escape(value or "")


def truncate(value: str, length: int) -> str:
    if len(value) <= length:
        return value
    return value[: length - 1].rstrip() + "…"


def safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", " ", name).strip() or "Camion"
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 2
    while candidate in used:
        tail = f" ({suffix})"
        candidate = f"{cleaned[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def split_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def join_lines(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line is not None)
