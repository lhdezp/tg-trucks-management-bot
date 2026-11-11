from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.callbacks import (
    DriverCB,
    MenuCB,
    ReportCB,
    SettingsCB,
    TicketCB,
    TripCB,
    TruckCB,
)
from app.config import get_settings
from app.keyboards import back_to_menu_row, button, markup
from app.models import BotSettings, Driver, Ticket, Trip, TripStatus, Truck
from app.services.weeks import day_name
from app.utils import (
    format_date,
    format_duration,
    format_money,
    format_number,
    format_week_range,
    kind_label,
    safe_escape,
    status_label,
    truncate,
)

TICKET_KINDS = ["fuel", "maintenance", "other"]


def main_menu_view() -> tuple[str, InlineKeyboardMarkup]:
    from app.keyboards import main_menu_kb

    settings = get_settings()
    text = (
        "<b>Gestión de camiones</b>\n\n"
        "Administra viajes, camiones, conductores y tickets desde los botones.\n"
        f"Zona horaria: <code>{safe_escape(settings.timezone)}</code>"
    )
    return text, main_menu_kb()


def trips_menu_view() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "<b>Viajes</b>\n\n"
        "Registra un viaje nuevo o consulta los existentes para editarlos, "
        "cambiar su estado o adjuntar tickets."
    )
    from app.keyboards import trips_menu_kb

    return text, trips_menu_kb()


def trip_button_label(trip: Trip) -> str:
    prefix = "Finalizado" if trip.status == TripStatus.finished else "En curso"
    route = f"{trip.origin} a {trip.destination}"
    return truncate(
        f"{prefix} · {format_date(trip.trip_date)} · {trip.truck.name} · {route}",
        58,
    )


def trips_list_view(
    trips: list[Trip], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for trip in trips:
        rows.append([button(trip_button_label(trip), TripCB(action="view", trip_id=trip.id))])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", TripCB(action="list", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TripCB(action="list", page=page + 1)))
    if nav:
        rows.append(nav)

    rows.append([button("Nuevo viaje", MenuCB(action="trip_new"))])
    rows.append(back_to_menu_row())

    if trips:
        text = "<b>Viajes</b>\n\nSelecciona un viaje para ver o editar sus datos."
    else:
        text = "<b>Viajes</b>\n\nNo hay viajes registrados todavía."
    return text, markup(rows)


def trip_detail_view(trip: Trip) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    lines = [
        f"<b>Viaje #{trip.id}</b>",
        f"Estado: <b>{status_label(trip.status)}</b>",
        f"Fecha: {format_date(trip.trip_date)}",
        f"Camión: {safe_escape(trip.truck.name)} (#{trip.truck.id})",
        f"Conductor: {safe_escape(trip.driver.name)}",
        f"Ruta: {safe_escape(trip.origin)} → {safe_escape(trip.destination)}",
        f"Millas: {format_number(trip.distance_miles)}",
        f"Tiempo: {format_duration(trip.duration_minutes)}",
        f"Peso: {format_number(trip.cargo_weight)} {settings.weight_unit}",
        f"% Conductor: {format_number(trip.driver_percentage)}%",
        f"Pago de la carga: {format_money(trip.cargo_payment, settings.currency)}",
        f"Pago del conductor: {format_money(trip.driver_pay, settings.currency)}",
        f"Tickets: {len(trip.tickets)}",
        f"Gastos de tickets: {format_money(trip.ticket_expenses, settings.currency)}",
    ]
    if trip.tickets_without_amount:
        lines.append(f"Tickets sin monto: {trip.tickets_without_amount}")
        lines.append(
            "Ganancia neta parcial: "
            f"{format_money(trip.net_profit, settings.currency)}"
        )
    else:
        lines.append(
            f"Ganancia neta: {format_money(trip.net_profit, settings.currency)}"
        )
    if trip.notes:
        lines.append(f"Notas: {safe_escape(trip.notes)}")

    rows: list[list[InlineKeyboardButton]] = [
        [
            button("Editar", TripCB(action="edit", trip_id=trip.id)),
            button("Tickets", TripCB(action="ticket_menu", trip_id=trip.id)),
        ]
    ]
    if trip.status == TripStatus.in_progress:
        rows.append(
            [button("Marcar finalizado", TripCB(action="finish", trip_id=trip.id))]
        )
    else:
        rows.append(
            [button("Volver a en curso", TripCB(action="reopen", trip_id=trip.id))]
        )
    rows.append([button("Eliminar", TripCB(action="delete", trip_id=trip.id))])
    rows.append([button("Volver a viajes", TripCB(action="list"))])
    rows.append(back_to_menu_row())
    return "\n".join(lines), markup(rows)


def trip_delete_confirm_view(trip: Trip) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"<b>Eliminar viaje #{trip.id}</b>\n\n"
        f"Se eliminarán el viaje y sus {len(trip.tickets)} tickets.\n"
        "Esta acción no se puede deshacer."
    )
    rows = [
        [
            button(
                "Sí, eliminar",
                TripCB(action="delete_confirm", trip_id=trip.id),
            )
        ],
        [button("Cancelar", TripCB(action="view", trip_id=trip.id))],
    ]
    return text, markup(rows)


def truck_list_view(
    trucks: list[Truck], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for truck in trucks:
        suffix = "" if truck.active else " (inactivo)"
        rows.append(
            [
                button(
                    f"{truck.name} (#{truck.id}){suffix}",
                    TruckCB(action="view", truck_id=truck.id),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", TruckCB(action="list", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TruckCB(action="list", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Nuevo camión", MenuCB(action="trucks_new"))])
    rows.append(back_to_menu_row())
    text = (
        "<b>Camiones</b>\n\nSelecciona un camión para administrarlo."
        if trucks
        else "<b>Camiones</b>\n\nNo hay camiones registrados."
    )
    return text, markup(rows)


def truck_detail_view(trip_count: int, truck: Truck) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"<b>{safe_escape(truck.name)}</b>\n"
        f"ID: <code>{truck.id}</code>\n"
        f"Estado: {'Activo' if truck.active else 'Inactivo'}\n"
        f"Viajes asociados: {trip_count}"
    )
    row = [button("Renombrar", TruckCB(action="rename", truck_id=truck.id))]
    row.append(
        button(
            "Desactivar" if truck.active else "Activar",
            TruckCB(action="toggle", truck_id=truck.id),
        )
    )
    rows = [row]
    if trip_count == 0:
        rows.append(
            [button("Eliminar", TruckCB(action="delete", truck_id=truck.id))]
        )
    rows.append([button("Volver a camiones", TruckCB(action="list"))])
    rows.append(back_to_menu_row())
    return text, markup(rows)


def driver_list_view(
    drivers: list[Driver], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for driver in drivers:
        suffix = "" if driver.active else " (inactivo)"
        rows.append(
            [
                button(
                    f"{driver.name} (#{driver.id}){suffix}",
                    DriverCB(action="view", driver_id=driver.id),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", DriverCB(action="list", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", DriverCB(action="list", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Nuevo conductor", MenuCB(action="drivers_new"))])
    rows.append(back_to_menu_row())
    text = (
        "<b>Conductores</b>\n\nSelecciona un conductor para administrarlo."
        if drivers
        else "<b>Conductores</b>\n\nNo hay conductores registrados."
    )
    return text, markup(rows)


def driver_detail_view(
    trip_count: int, driver: Driver
) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"<b>{safe_escape(driver.name)}</b>\n"
        f"ID: <code>{driver.id}</code>\n"
        f"Teléfono: {safe_escape(driver.phone) if driver.phone else 'No indicado'}\n"
        f"Estado: {'Activo' if driver.active else 'Inactivo'}\n"
        f"Viajes asociados: {trip_count}"
    )
    row = [
        button("Renombrar", DriverCB(action="rename", driver_id=driver.id)),
        button("Teléfono", DriverCB(action="phone", driver_id=driver.id)),
    ]
    rows = [row]
    rows.append(
        [
            button(
                "Desactivar" if driver.active else "Activar",
                DriverCB(action="toggle", driver_id=driver.id),
            )
        ]
    )
    if trip_count == 0:
        rows.append(
            [button("Eliminar", DriverCB(action="delete", driver_id=driver.id))]
        )
    rows.append([button("Volver a conductores", DriverCB(action="list"))])
    rows.append(back_to_menu_row())
    return text, markup(rows)


def ticket_trip_list_view(
    trips: list[Trip], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for trip in trips:
        label = truncate(
            f"#{trip.id} · {format_date(trip.trip_date)} · {trip.truck.name} · "
            f"{len(trip.tickets)} tickets",
            58,
        )
        rows.append([button(label, TicketCB(action="menu", trip_id=trip.id))])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", TicketCB(action="list", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TicketCB(action="list", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append(back_to_menu_row())
    text = (
        "<b>Tickets</b>\n\nElige el viaje al que quieres administrarle los tickets."
        if trips
        else "<b>Tickets</b>\n\nNo hay viajes registrados."
    )
    return text, markup(rows)


def ticket_counts(tickets: list[Ticket]) -> dict[str, int]:
    counts = {kind: 0 for kind in TICKET_KINDS}
    for ticket in tickets:
        counts[ticket.kind.value] = counts.get(ticket.kind.value, 0) + 1
    return counts


def ticket_menu_view(trip: Trip) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    counts = ticket_counts(list(trip.tickets))
    total = len(trip.tickets)
    lines = [
        f"<b>Tickets del viaje #{trip.id}</b>",
        f"{format_date(trip.trip_date)} A� {safe_escape(trip.truck.name)}",
        f"Total: {total}",
        f"Gastos: {format_money(trip.ticket_expenses, settings.currency)}",
    ]
    if trip.tickets_without_amount:
        lines.append(f"Sin monto: {trip.tickets_without_amount}")
    lines.extend(
        [
            "",
            f"Gasolina: {counts.get('fuel', 0)}",
            f"Mantenimiento: {counts.get('maintenance', 0)}",
            f"Otro: {counts.get('other', 0)}",
        ]
    )
    rows: list[list[InlineKeyboardButton]] = [
        [button("Agregar imA�genes", TicketCB(action="add", trip_id=trip.id))]
    ]
    if total:
        rows.append(
            [button("Ver y editar montos", TicketCB(action="amounts", trip_id=trip.id))]
        )
        rows.append(
            [button("Reenviar todos", TicketCB(action="resend_all", trip_id=trip.id))]
        )
        for kind in TICKET_KINDS:
            count = counts.get(kind, 0)
            if count:
                rows.append(
                    [
                        button(
                            f"Reenviar {kind_label_from_value(kind).lower()} ({count})",
                            TicketCB(
                                action="resend_kind",
                                trip_id=trip.id,
                                value=kind,
                            ),
                        )
                    ]
                )
    rows.append([button("Ver viaje", TripCB(action="view", trip_id=trip.id))])
    rows.append([button("Volver a tickets", TicketCB(action="list"))])
    rows.append(back_to_menu_row())
    return "\n".join(lines), markup(rows)


def kind_label_from_value(value: str) -> str:
    from app.models import TicketKind

    return kind_label(TicketKind(value))


def ticket_add_kb(trip_id: int) -> InlineKeyboardMarkup:
    rows = [
        [button("Gasolina", TicketCB(action="kind", trip_id=trip_id, value="fuel"))],
        [
            button(
                "Mantenimiento",
                TicketCB(action="kind", trip_id=trip_id, value="maintenance"),
            )
        ],
        [button("Otro", TicketCB(action="kind", trip_id=trip_id, value="other"))],
        [button("Volver", TicketCB(action="menu", trip_id=trip_id))],
    ]
    return markup(rows)


def ticket_amounts_view(
    trip: Trip,
    tickets: list[Ticket],
    page: int,
    has_next: bool,
) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = []
    for ticket in tickets:
        if ticket.amount is None:
            amount = "sin monto"
        else:
            amount = format_money(ticket.amount, settings.currency)
        label = truncate(
            f"#{ticket.id} - {kind_label(ticket.kind)} - {amount}",
            58,
        )
        rows.append(
            [
                button(
                    label,
                    TicketCB(
                        action="amount_edit",
                        trip_id=trip.id,
                        value=str(ticket.id),
                    ),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            button(
                "Anterior",
                TicketCB(action="amounts", trip_id=trip.id, page=page - 1),
            )
        )
    if has_next:
        nav.append(
            button(
                "Siguiente",
                TicketCB(action="amounts", trip_id=trip.id, page=page + 1),
            )
        )
    if nav:
        rows.append(nav)
    rows.append([button("Volver", TicketCB(action="menu", trip_id=trip.id))])
    text = (
        f"<b>Montos de tickets del viaje #{trip.id}</b>\n"
        f"Gastos actuales: {format_money(trip.ticket_expenses, settings.currency)}\n"
        f"Sin monto: {trip.tickets_without_amount}\n\n"
        "Elige un ticket para corregir su monto o volver a analizarlo."
    )
    return text, markup(rows)


def ticket_amount_prompt_view(
    ticket: Ticket, note: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    current = (
        "Sin monto"
        if ticket.amount is None
        else format_money(ticket.amount, settings.currency)
    )
    source = {
        "ai": "detectado por IA",
        "manual": "cargado manualmente",
    }.get(ticket.amount_source or "", "sin definir")
    text = (
        f"<b>Ticket #{ticket.id}</b>\n"
        f"Categoria: {kind_label(ticket.kind)}\n"
        f"Monto actual: {current} ({source})\n\n"
        "Escribe el monto total del ticket o usa los botones."
    )
    if note:
        text = f"{text}\n\n{note}"
    rows = [
        [
            button(
                "Reanalizar con IA",
                TicketCB(
                    action="retry_ai",
                    trip_id=ticket.trip_id,
                    value=str(ticket.id),
                ),
            )
        ]
    ]
    if ticket.amount is not None:
        rows.append(
            [
                button(
                    "Quitar monto",
                    TicketCB(
                        action="amount_clear",
                        trip_id=ticket.trip_id,
                        value=str(ticket.id),
                    ),
                )
            ]
        )
    rows.append(
        [button("Volver", TicketCB(action="amounts", trip_id=ticket.trip_id))]
    )
    return text, markup(rows)


def report_menu_view() -> tuple[str, InlineKeyboardMarkup]:
    from app.keyboards import reports_menu_kb

    text = (
        "<b>Reportes</b>\n\n"
        "El Excel siempre incluye tres hojas: Finalizados, En curso y Ambos.\n"
        "Puedes generar un reporte general o elegir un camión."
    )
    return text, reports_menu_kb()


def report_week_view(
    scope: str, truck_id: int, truck_name: str | None
) -> tuple[str, InlineKeyboardMarkup]:
    from app.services.weeks import current_week_bounds, previous_week_bounds

    current_start, current_end = current_week_bounds()
    previous_start, previous_end = previous_week_bounds()
    scope_label = (
        f"Camión: {safe_escape(truck_name)}"
        if scope == "truck" and truck_name
        else "General"
    )
    text = (
        f"<b>Elegir semana</b>\n\nAlcance: {scope_label}\n"
        f"Semana actual: {format_week_range(current_start, current_end)}\n"
        f"Semana pasada: {format_week_range(previous_start, previous_end)}"
    )
    rows = [
        [
            button(
                "Semana actual",
                ReportCB(
                    action="week",
                    scope=scope,
                    week="current",
                    truck_id=truck_id,
                ),
            )
        ],
        [
            button(
                "Semana pasada",
                ReportCB(
                    action="week",
                    scope=scope,
                    week="previous",
                    truck_id=truck_id,
                ),
            )
        ],
        [
            button(
                "Otra fecha",
                ReportCB(action="custom", scope=scope, truck_id=truck_id),
            )
        ],
    ]
    rows.append(
        [
            button(
                "Volver",
                ReportCB(action="scope_menu")
                if scope == "general"
                else ReportCB(action="truck_scope"),
            )
        ]
    )
    rows.append(back_to_menu_row())
    return text, markup(rows)


def report_truck_list_view(
    trucks: list[Truck], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for truck in trucks:
        suffix = "" if truck.active else " (inactivo)"
        rows.append(
            [
                button(
                    f"{truck.name} (#{truck.id}){suffix}",
                    ReportCB(action="truck", truck_id=truck.id),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", ReportCB(action="truck_scope", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", ReportCB(action="truck_scope", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Volver a reportes", MenuCB(action="reports"))])
    rows.append(back_to_menu_row())
    text = (
        "<b>Reporte por camión</b>\n\nElige el camión."
        if trucks
        else "<b>Reporte por camión</b>\n\nNo hay camiones registrados."
    )
    return text, markup(rows)


def settings_view(
    config: BotSettings, truck_name: str | None
) -> tuple[str, InlineKeyboardMarkup]:
    settings = get_settings()
    if config.report_scope == "truck" and truck_name:
        scope_text = f"Camión: {truck_name}"
    elif config.report_scope == "truck":
        scope_text = "Camión no encontrado (se usará general)"
    else:
        scope_text = "General"
    destination = (
        f"Chat configurado ({config.report_chat_id})"
        if config.report_chat_id
        else "Administradores (respaldo)"
    )
    text = (
        "<b>Configuración del reporte automático</b>\n\n"
        f"Zona horaria: <code>{safe_escape(settings.timezone)}</code>\n"
        f"Estado: {'Activado' if config.report_enabled else 'Desactivado'}\n"
        f"Día: {day_name(config.report_day)}\n"
        f"Hora: {config.report_time}\n"
        f"Alcance: {safe_escape(scope_text)}\n"
        f"Destino: {safe_escape(destination)}"
    )
    rows = [
        [
            button("Cambiar día", SettingsCB(action="day_menu")),
            button("Cambiar hora", SettingsCB(action="time_menu")),
        ],
        [button("Cambiar alcance", SettingsCB(action="scope_menu"))],
        [
            button(
                "Desactivar" if config.report_enabled else "Activar",
                SettingsCB(action="toggle"),
            ),
            button("Destino: este chat", SettingsCB(action="chat")),
        ],
        [button("Enviar prueba", SettingsCB(action="test"))],
        back_to_menu_row(),
    ]
    return text, markup(rows)


def day_menu_kb() -> InlineKeyboardMarkup:
    from app.services.weeks import DAY_NAMES

    rows = [
        [button(DAY_NAMES[index], SettingsCB(action="day", value=str(index)))]
        for index in range(7)
    ]
    rows.append([button("Volver", SettingsCB(action="show"))])
    return markup(rows)


def time_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            button("06:00", SettingsCB(action="time", value="06:00")),
            button("08:00", SettingsCB(action="time", value="08:00")),
            button("09:00", SettingsCB(action="time", value="09:00")),
        ],
        [
            button("12:00", SettingsCB(action="time", value="12:00")),
            button("18:00", SettingsCB(action="time", value="18:00")),
            button("20:00", SettingsCB(action="time", value="20:00")),
        ],
        [button("Otra hora", SettingsCB(action="time_custom"))],
        [button("Volver", SettingsCB(action="show"))],
    ]
    return markup(rows)


def scope_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [button("General", SettingsCB(action="scope", value="general"))],
        [button("Por camión", SettingsCB(action="scope", value="truck"))],
        [button("Volver", SettingsCB(action="show"))],
    ]
    return markup(rows)


def settings_truck_list_view(
    trucks: list[Truck], page: int, has_next: bool
) -> tuple[str, InlineKeyboardMarkup]:
    rows: list[list[InlineKeyboardButton]] = []
    for truck in trucks:
        suffix = "" if truck.active else " (inactivo)"
        rows.append(
            [
                button(
                    f"{truck.name} (#{truck.id}){suffix}",
                    SettingsCB(action="truck", value=str(truck.id)),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(button("Anterior", SettingsCB(action="scope_truck", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", SettingsCB(action="scope_truck", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Volver", SettingsCB(action="show"))])
    text = (
        "<b>Elegir camión para el reporte automático</b>"
        if trucks
        else "<b>Elegir camión</b>\n\nNo hay camiones registrados."
    )
    return text, markup(rows)
