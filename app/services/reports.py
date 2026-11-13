from __future__ import annotations

import asyncio
import os
import tempfile
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import Settings, get_settings
from app.database import session_scope
from app.models import Ticket, Trip, TripStatus
from app.services.queries import get_truck, trips_for_report
from app.utils import (
    format_date,
    format_duration,
    format_money,
    format_number,
    format_week_range,
    safe_escape,
    split_text,
    status_label,
)

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
TOTAL_FILL = PatternFill("solid", fgColor="D9E2F3")
EMPTY_FILL = PatternFill("solid", fgColor="F2F2F2")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)

SHEET_DEFINITIONS = [
    ("finished", "Finalizados", TripStatus.finished, False),
    ("in_progress", "En curso", TripStatus.in_progress, False),
    ("all", "Ambos", None, True),
]


def _decimal_sum(trips: list[Trip], attribute: str) -> Decimal:
    return sum((getattr(trip, attribute) for trip in trips), Decimal("0"))


def _ticket_count(tickets: list[Ticket]) -> int:
    return len(tickets)


def _headers(settings: Settings, include_status: bool) -> list[str]:
    headers = [
        "Fecha",
        "Camión",
        "Conductor",
        "Origen",
        "Destino",
        "Millas",
        "Tiempo",
        f"Peso ({settings.weight_unit})",
        "% Conductor",
        f"Pago carga ({settings.currency})",
        f"Pago conductor ({settings.currency})",
        f"Gastos tickets ({settings.currency})",
        f"Ganancia neta ({settings.currency})",
        "Tickets",
        "Tickets sin monto",
        "Tickets sin confirmar",
        "Notas",
    ]
    if include_status:
        headers.insert(3, "Estado")
    return headers


def _column_index(headers: list[str]) -> dict[str, int]:
    return {name: index + 1 for index, name in enumerate(headers)}


def _style_header(ws, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = ws.cell(row=row, column=column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 22


def _write_title(ws, text: str, columns: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    cell = ws.cell(row=1, column=1, value=text)
    cell.font = TITLE_FONT
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24


def _set_widths(ws, headers: list[str]) -> None:
    settings = get_settings()
    widths = {
        "Fecha": 12,
        "Camión": 28,
        "Conductor": 22,
        "Estado": 14,
        "Origen": 22,
        "Destino": 22,
        "Millas": 10,
        "Tiempo": 10,
        f"Peso ({settings.weight_unit})": 14,
        "% Conductor": 12,
        f"Pago carga ({settings.currency})": 16,
        f"Pago conductor ({settings.currency})": 18,
        f"Gastos tickets ({settings.currency})": 18,
        f"Ganancia neta ({settings.currency})": 18,
        "Tickets": 9,
        "Tickets sin monto": 16,
        "Tickets sin confirmar": 18,
        "Notas": 42,
    }
    for index, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(index)].width = widths.get(header, 14)


def _write_trip_row(ws, row: int, trip: Trip, headers: list[str], include_status: bool) -> None:
    settings = get_settings()
    columns = _column_index(headers)
    values = {
        "Fecha": trip.trip_date,
        "Camión": f"{trip.truck.name} (#{trip.truck.id})",
        "Conductor": trip.driver.name,
        "Estado": status_label(trip.status),
        "Origen": trip.origin,
        "Destino": trip.destination,
        "Millas": float(trip.distance_miles),
        "Tiempo": format_duration(trip.duration_minutes),
        f"Peso ({settings.weight_unit})": float(trip.cargo_weight),
        "% Conductor": float(trip.driver_percentage) / 100,
        f"Pago carga ({settings.currency})": float(trip.cargo_payment),
        f"Pago conductor ({settings.currency})": float(trip.driver_pay),
        f"Gastos tickets ({settings.currency})": float(trip.ticket_expenses),
        f"Ganancia neta ({settings.currency})": float(trip.net_profit),
        "Tickets": _ticket_count(list(trip.tickets)),
        "Tickets sin monto": trip.tickets_without_amount,
        "Tickets sin confirmar": trip.tickets_pending_confirmation,
        "Notas": trip.notes or "",
    }

    for header, column in columns.items():
        cell = ws.cell(row=row, column=column, value=values.get(header, ""))
        cell.border = THIN_BORDER
        cell.alignment = Alignment(vertical="top", wrap_text=header == "Notas")
        if header == "Fecha":
            cell.number_format = "dd/mm/yyyy"
        elif header == "Millas":
            cell.number_format = "#,##0.00"
        elif header.startswith("Peso"):
            cell.number_format = "#,##0.00"
        elif header == "% Conductor":
            cell.number_format = "0.00%"
        elif header.startswith("Pago"):
            cell.number_format = "#,##0.00"
        elif header.startswith("Gastos") or header.startswith("Ganancia"):
            cell.number_format = "#,##0.00"
        elif header.startswith("Tickets"):
            cell.number_format = "0"


def _write_total_row(
    ws,
    row: int,
    label: str,
    trips: list[Trip],
    headers: list[str],
    total_fill: PatternFill,
) -> None:
    settings = get_settings()
    columns = _column_index(headers)
    values = {
        "Camión": label,
        "Millas": float(_decimal_sum(trips, "distance_miles")),
        "Tiempo": format_duration(sum(trip.duration_minutes for trip in trips)),
        f"Peso ({settings.weight_unit})": float(_decimal_sum(trips, "cargo_weight")),
        f"Pago carga ({settings.currency})": float(_decimal_sum(trips, "cargo_payment")),
        f"Pago conductor ({settings.currency})": float(
            sum((trip.driver_pay for trip in trips), Decimal("0"))
        ),
        f"Gastos tickets ({settings.currency})": float(
            _decimal_sum(trips, "ticket_expenses")
        ),
        f"Ganancia neta ({settings.currency})": float(
            _decimal_sum(trips, "net_profit")
        ),
        "Tickets": sum(_ticket_count(list(trip.tickets)) for trip in trips),
        "Tickets sin monto": sum(trip.tickets_without_amount for trip in trips),
        "Tickets sin confirmar": sum(
            trip.tickets_pending_confirmation for trip in trips
        ),
    }
    for column in range(1, len(headers) + 1):
        cell = ws.cell(row=row, column=column)
        cell.fill = total_fill
        cell.font = Font(bold=True)
        cell.border = THIN_BORDER
    for header, column in columns.items():
        value = values.get(header)
        if value not in (None, ""):
            cell = ws.cell(row=row, column=column, value=value)
            if header == "Millas" or header.startswith("Peso"):
                cell.number_format = "#,##0.00"
            elif header.startswith("Pago"):
                cell.number_format = "#,##0.00"
            elif header.startswith("Gastos") or header.startswith("Ganancia"):
                cell.number_format = "#,##0.00"
            elif header.startswith("Tickets"):
                cell.number_format = "0"
    ws.cell(row=row, column=columns["Camión"]).alignment = Alignment(
        horizontal="left", vertical="center"
    )


def _build_status_sheet(
    wb: Workbook,
    title: str,
    trips: list[Trip],
    week_start: date,
    week_end: date,
    scope_label: str,
    include_status: bool,
    grouped: bool,
) -> None:
    settings = get_settings()
    ws = wb.create_sheet(title=title)
    headers = _headers(settings, include_status)
    _set_widths(ws, headers)
    _write_title(
        ws,
        f"{scope_label} · {format_week_range(week_start, week_end)}",
        len(headers),
    )
    for index, header in enumerate(headers, start=1):
        ws.cell(row=2, column=index, value=header)
    _style_header(ws, 2, len(headers))

    if not trips:
        ws.merge_cells(
            start_row=3,
            start_column=1,
            end_row=3,
            end_column=len(headers),
        )
        cell = ws.cell(row=3, column=1, value="Sin viajes en esta categoría.")
        cell.fill = EMPTY_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A3"
        return

    row = 3
    if grouped:
        groups: dict[int, list[Trip]] = defaultdict(list)
        for trip in trips:
            groups[trip.truck.id].append(trip)
        for group_trips in groups.values():
            for trip in group_trips:
                _write_trip_row(ws, row, trip, headers, include_status)
                row += 1
            _write_total_row(
                ws,
                row,
                f"Subtotal {group_trips[0].truck.name}",
                group_trips,
                headers,
                TOTAL_FILL,
            )
            row += 1
        if len(groups) > 1:
            _write_total_row(ws, row, "Total general", trips, headers, TOTAL_FILL)
            row += 1
    else:
        for trip in trips:
            _write_trip_row(ws, row, trip, headers, include_status)
            row += 1
        _write_total_row(ws, row, "Total", trips, headers, TOTAL_FILL)

    ws.freeze_panes = "A3"


def build_workbook(
    trips: list[Trip],
    week_start: date,
    week_end: date,
    scope_label: str,
    *,
    general: bool,
) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    for _key, title, status, include_status in SHEET_DEFINITIONS:
        filtered = [
            trip for trip in trips if status is None or trip.status == status
        ]
        _build_status_sheet(
            wb,
            title,
            filtered,
            week_start,
            week_end,
            scope_label,
            include_status,
            grouped=general,
        )
    wb.properties.title = scope_label
    wb.properties.creator = "Gestión de camiones"

    descriptor, path = tempfile.mkstemp(prefix="reporte_camiones_", suffix=".xlsx")
    os.close(descriptor)
    result = Path(path)
    wb.save(result)
    return result


def report_filename(
    week_start: date,
    week_end: date,
    *,
    general: bool,
    truck_id: int | None = None,
) -> str:
    prefix = "reporte_general" if general else f"reporte_camion_{truck_id}"
    return (
        f"{prefix}_{week_start.isoformat()}_a_{week_end.isoformat()}.xlsx"
    )


async def send_report(
    bot: Bot,
    chat_id: int,
    trips: list[Trip],
    week_start: date,
    week_end: date,
    *,
    general: bool,
    scope_label: str,
    truck_id: int | None = None,
) -> bool:
    if not trips:
        await bot.send_message(
            chat_id,
            f"No hay viajes registrados para {scope_label.lower()} "
            f"en la semana del {format_week_range(week_start, week_end)}.",
        )
        return True

    path = await asyncio.to_thread(
        build_workbook,
        trips,
        week_start,
        week_end,
        scope_label,
        general=general,
    )
    filename = report_filename(
        week_start, week_end, general=general, truck_id=truck_id
    )
    try:
        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(path, filename=filename),
            caption=(
                f"{scope_label}\n"
                f"Semana: {format_week_range(week_start, week_end)}\n"
                "Hojas: Finalizados, En curso y Ambos."
            ),
        )
        return True
    finally:
        path.unlink(missing_ok=True)


async def send_week_report(
    bot: Bot,
    chat_id: int,
    week_start: date,
    week_end: date,
    *,
    scope: str,
    truck_id: int | None = None,
) -> bool:
    with session_scope() as db:
        truck = get_truck(db, truck_id) if scope == "truck" and truck_id else None
        if scope == "truck" and truck is None:
            await bot.send_message(chat_id, "El camión seleccionado ya no existe.")
            return False
        trips = trips_for_report(
            db,
            week_start,
            week_end,
            None if truck is None else truck.id,
        )
        general = truck is None
        scope_label = (
            "Reporte general"
            if general
            else f"Reporte del camión {truck.name}"
        )
        report_truck_id = None if general else truck.id

    return await send_report(
        bot,
        chat_id,
        trips,
        week_start,
        week_end,
        general=general,
        scope_label=scope_label,
        truck_id=report_truck_id,
    )


def build_summary_text(
    trips: list[Trip],
    week_start: date,
    week_end: date,
) -> str:
    settings = get_settings()
    if not trips:
        return (
            "<b>Resumen semanal</b>\n"
            f"Semana: {format_week_range(week_start, week_end)}\n\n"
            "No hay viajes registrados en esta semana."
        )

    groups: dict[int, list[Trip]] = defaultdict(list)
    for trip in trips:
        groups[trip.truck.id].append(trip)

    lines = [
        "<b>Resumen semanal</b>",
        f"Semana: {format_week_range(week_start, week_end)}",
        f"Total de viajes: {len(trips)}",
        "",
    ]

    for group_trips in groups.values():
        finished = sum(1 for trip in group_trips if trip.status == TripStatus.finished)
        in_progress = len(group_trips) - finished
        truck = group_trips[0].truck
        ticket_total = sum(len(trip.tickets) for trip in group_trips)
        pending_total = sum(trip.tickets_without_amount for trip in group_trips)
        pending_confirm_total = sum(
            trip.tickets_pending_confirmation for trip in group_trips
        )
        net_label = (
            "Ganancia neta parcial"
            if pending_total or pending_confirm_total
            else "Ganancia neta"
        )
        lines.extend(
            [
                f"<b>{safe_escape(truck.name)}</b> (#{truck.id})",
                (
                    f"Viajes: {len(group_trips)} "
                    f"(Finalizados: {finished} · En curso: {in_progress})"
                ),
                f"Millas: {format_number(_decimal_sum(group_trips, 'distance_miles'))}",
                (
                    "Tiempo: "
                    f"{format_duration(sum(trip.duration_minutes for trip in group_trips))}"
                ),
                (
                    f"Peso: {format_number(_decimal_sum(group_trips, 'cargo_weight'))} "
                    f"{settings.weight_unit}"
                ),
                (
                    "Pago de carga: "
                    f"{format_money(_decimal_sum(group_trips, 'cargo_payment'), settings.currency)}"
                ),
                (
                    "Pago conductores: "
                    f"{format_money(sum((trip.driver_pay for trip in group_trips), Decimal('0')), settings.currency)}"
                ),
                (
                    "Gastos de tickets: "
                    f"{format_money(_decimal_sum(group_trips, 'ticket_expenses'), settings.currency)}"
                ),
                (
                    f"{net_label}: "
                    f"{format_money(_decimal_sum(group_trips, 'net_profit'), settings.currency)}"
                ),
                (
                    f"Tickets: {ticket_total} (sin monto: {pending_total}, "
                    f"sin confirmar: {pending_confirm_total})"
                ),
                "",
            ]
        )

    finished_total = sum(1 for trip in trips if trip.status == TripStatus.finished)
    pending_total = sum(trip.tickets_without_amount for trip in trips)
    pending_confirm_total = sum(
        trip.tickets_pending_confirmation for trip in trips
    )
    net_label = (
        "Ganancia neta parcial"
        if pending_total or pending_confirm_total
        else "Ganancia neta"
    )
    lines.extend(
        [
            "<b>Totales</b>",
            f"Viajes: {len(trips)} (Finalizados: {finished_total} · En curso: {len(trips) - finished_total})",
            f"Millas: {format_number(_decimal_sum(trips, 'distance_miles'))}",
            f"Tiempo: {format_duration(sum(trip.duration_minutes for trip in trips))}",
            (
                f"Peso: {format_number(_decimal_sum(trips, 'cargo_weight'))} "
                f"{settings.weight_unit}"
            ),
            (
                "Pago de carga: "
                f"{format_money(_decimal_sum(trips, 'cargo_payment'), settings.currency)}"
            ),
            (
                "Pago conductores: "
                f"{format_money(sum((trip.driver_pay for trip in trips), Decimal('0')), settings.currency)}"
            ),
            (
                "Gastos de tickets: "
                f"{format_money(_decimal_sum(trips, 'ticket_expenses'), settings.currency)}"
            ),
            (
                f"{net_label}: "
                f"{format_money(_decimal_sum(trips, 'net_profit'), settings.currency)}"
            ),
            (
                f"Tickets: sin monto: {pending_total}, "
                f"sin confirmar: {pending_confirm_total}"
            ),
        ]
    )
    return "\n".join(lines)


async def send_summary(
    bot: Bot,
    chat_id: int,
    trips: list[Trip],
    week_start: date,
    week_end: date,
) -> None:
    text = build_summary_text(trips, week_start, week_end)
    for chunk in split_text(text):
        await bot.send_message(chat_id, chunk)
