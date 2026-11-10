from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import MenuCB, TripCB
from app.config import get_settings
from app.database import session_scope
from app.keyboards import button, markup
from app.models import Driver, Trip, TripStatus, Truck
from app.services.queries import (
    all_active_drivers,
    all_active_trucks,
    all_drivers,
    all_trucks,
    create_trip,
    delete_trip,
    get_driver,
    get_trip,
    get_truck,
    list_trips,
    list_trucks,
    list_drivers,
    update_trip,
)
from app.services.weeks import today_local
from app.states import TripCreate, TripEdit
from app.ui import edit_or_send, remember_ui_message, set_ui_message
from app.utils import (
    FIELD_LABELS,
    format_date,
    format_duration,
    format_money,
    format_number,
    parse_date_text,
    parse_decimal,
    parse_duration_minutes,
)
from app.views import (
    trips_list_view,
    trips_menu_view,
    trip_delete_confirm_view,
    trip_detail_view,
)

router = Router(name="trips")

CREATE_FIELDS = [
    "origin",
    "destination",
    "distance",
    "duration",
    "weight",
    "percentage",
    "payment",
]

EDIT_FIELDS = [
    "truck",
    "driver",
    "origin",
    "destination",
    "distance",
    "duration",
    "weight",
    "percentage",
    "payment",
    "date",
    "status",
    "notes",
]


def cancel_kb():
    return markup(
        [
            [button("Atrás", TripCB(action="back")), button("Cancelar", MenuCB(action="cancel"))]
        ]
    )


def date_kb() -> object:
    today = today_local()
    yesterday = today - timedelta(days=1)
    return markup(
        [
            [
                button(
                    f"Hoy ({format_date(today)})",
                    TripCB(action="date", value="today"),
                )
            ],
            [
                button(
                    f"Ayer ({format_date(yesterday)})",
                    TripCB(action="date", value="yesterday"),
                )
            ],
            [button("Otra fecha", TripCB(action="date", value="custom"))],
            [button("Atrás", TripCB(action="back")), button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def status_kb() -> object:
    return markup(
        [
            [
                button(
                    "En curso",
                    TripCB(action="status", value=TripStatus.in_progress.value),
                )
            ],
            [
                button(
                    "Finalizado",
                    TripCB(action="status", value=TripStatus.finished.value),
                )
            ],
            [button("Atrás", TripCB(action="back")), button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def edit_date_kb() -> object:
    today = today_local()
    yesterday = today - timedelta(days=1)
    return markup(
        [
            [
                button(
                    f"Hoy ({format_date(today)})",
                    TripCB(action="edit_date", value="today"),
                )
            ],
            [
                button(
                    f"Ayer ({format_date(yesterday)})",
                    TripCB(action="edit_date", value="yesterday"),
                )
            ],
            [button("Otra fecha", TripCB(action="edit_date", value="custom"))],
            [button("Volver", TripCB(action="edit_back"))],
        ]
    )


def edit_status_kb() -> object:
    return markup(
        [
            [
                button(
                    "En curso",
                    TripCB(action="edit_status", value=TripStatus.in_progress.value),
                )
            ],
            [
                button(
                    "Finalizado",
                    TripCB(action="edit_status", value=TripStatus.finished.value),
                )
            ],
            [button("Volver", TripCB(action="edit_back"))],
        ]
    )


def notes_kb() -> object:
    return markup(
        [
            [button("Omitir notas", TripCB(action="notes_skip"))],
            [button("Atrás", TripCB(action="back")), button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def confirm_kb() -> object:
    return markup(
        [
            [button("Confirmar y guardar", TripCB(action="confirm"))],
            [button("Atrás", TripCB(action="back")), button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def _field_prompt(field: str) -> str:
    settings = get_settings()
    prompts = {
        "origin": "Escribe el origen del viaje.",
        "destination": "Escribe el destino del viaje.",
        "distance": "Escribe las millas recorridas (ej. 125.5).",
        "duration": "Escribe el tiempo del viaje (ej. 8:30 u 8.5 horas).",
        "weight": f"Escribe el peso de la carga en {settings.weight_unit} (ej. 12000).",
        "percentage": "Escribe el porcentaje para el conductor (0 a 100).",
        "payment": f"Escribe el pago de la carga en {settings.currency} (ej. 1500).",
        "notes": "Escribe las notas del viaje o pulsa Omitir.",
        "date": "Escribe la fecha del viaje (DD/MM/AAAA).",
    }
    return prompts[field]


async def _delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def validate_trip_field(field: str, raw: str) -> tuple[object | None, str | None]:
    settings = get_settings()
    if field in ("origin", "destination"):
        value = raw.strip()
        if not value:
            return None, "El dato no puede estar vacío."
        if len(value) > 160:
            return None, "El dato es demasiado largo (máximo 160 caracteres)."
        return value, None

    if field == "distance":
        value = parse_decimal(raw)
        if value is None or value <= 0:
            return None, "Las millas deben ser un número mayor a cero."
        if value > Decimal("100000"):
            return None, "Las millas parecen fuera de rango."
        return value.quantize(Decimal("0.01")), None

    if field == "duration":
        minutes = parse_duration_minutes(raw)
        if minutes is None:
            return None, "El tiempo debe ser mayor a cero. Ejemplos: 8:30, 8.5 u 8h 30m."
        if minutes > 525600:
            return None, "El tiempo parece fuera de rango."
        return minutes, None

    if field == "weight":
        value = parse_decimal(raw)
        if value is None or value <= 0:
            return None, f"El peso debe ser un número mayor a cero ({settings.weight_unit})."
        return value.quantize(Decimal("0.01")), None

    if field == "percentage":
        value = parse_decimal(raw)
        if value is None or value < 0 or value > 100:
            return None, "El porcentaje debe estar entre 0 y 100."
        return value.quantize(Decimal("0.01")), None

    if field == "payment":
        value = parse_decimal(raw)
        if value is None or value < 0:
            return None, "El pago debe ser un número mayor o igual a cero."
        return value.quantize(Decimal("0.01")), None

    if field == "date":
        value = parse_date_text(raw)
        if value is None:
            return None, "Fecha inválida. Usa el formato DD/MM/AAAA."
        if value > today_local():
            return None, "La fecha no puede ser futura."
        return value, None

    if field == "notes":
        value = raw.strip()
        if len(value) > 1000:
            return None, "Las notas son demasiado largas (máximo 1000 caracteres)."
        return value or None, None

    return None, "Campo desconocido."


async def _ask_create_field(
    message: Message,
    state: FSMContext,
    field: str,
    error: str | None = None,
) -> None:
    await state.set_state(TripCreate.input)
    await state.update_data(current_field=field)
    text = _field_prompt(field)
    if error:
        text = f"<b>{error}</b>\n\n{text}"
    await set_ui_message(message, state, text, cancel_kb())


async def _ask_date(message: Message, state: FSMContext) -> None:
    await state.set_state(TripCreate.date)
    await set_ui_message(
        message, state, "¿Cuál es la fecha del viaje?", date_kb()
    )


async def _ask_status(message: Message, state: FSMContext) -> None:
    await state.set_state(TripCreate.status)
    await set_ui_message(
        message, state, "¿Cuál es el estado del viaje?", status_kb()
    )


async def _ask_notes(message: Message, state: FSMContext) -> None:
    await state.set_state(TripCreate.notes)
    await set_ui_message(message, state, _field_prompt("notes"), notes_kb())


def _confirm_text(data: dict) -> str:
    settings = get_settings()
    payment = Decimal(str(data["payment"]))
    percentage = Decimal(str(data["percentage"]))
    driver_pay = (payment * percentage / Decimal(100)).quantize(Decimal("0.01"))
    status = TripStatus(data["status"])
    return (
        "<b>Confirmar viaje</b>\n\n"
        f"Camión: {data['truck_name']} (#{data['truck_id']})\n"
        f"Conductor: {data['driver_name']}\n"
        f"Fecha: {format_date(date.fromisoformat(data['trip_date']))}\n"
        f"Estado: {'Finalizado' if status == TripStatus.finished else 'En curso'}\n"
        f"Ruta: {data['origin']} → {data['destination']}\n"
        f"Millas: {format_number(data['distance'])}\n"
        f"Tiempo: {format_duration(int(data['duration']))}\n"
        f"Peso: {format_number(data['weight'])} {settings.weight_unit}\n"
        f"% Conductor: {format_number(data['percentage'])}%\n"
        f"Pago de la carga: {format_money(payment, settings.currency)}\n"
        f"Pago del conductor: {format_money(driver_pay, settings.currency)}"
    )


async def _show_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(TripCreate.confirm)
    await set_ui_message(message, state, _confirm_text(data), confirm_kb())


async def _show_truck_selection(
    message: Message, state: FSMContext, page: int = 0
) -> None:
    with session_scope() as db:
        trucks, has_next = list_trucks(db, page, active_only=True)
    rows = [
        [
            button(
                f"{truck.name} (#{truck.id})",
                TripCB(action="truck_set", value=str(truck.id)),
            )
        ]
        for truck in trucks
    ]
    nav = []
    if page > 0:
        nav.append(button("Anterior", TripCB(action="truck_page", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TripCB(action="truck_page", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Cancelar", MenuCB(action="cancel"))])
    await state.set_state(TripCreate.truck)
    text = "<b>Nuevo viaje</b>\n\nElige el camión."
    if not trucks:
        text = (
            "<b>Nuevo viaje</b>\n\n"
            "No hay camiones activos. Crea un camión primero."
        )
        rows.insert(0, [button("Crear camión", MenuCB(action="trucks_new"))])
    await set_ui_message(message, state, text, markup(rows))


async def _show_driver_selection(
    message: Message, state: FSMContext, page: int = 0
) -> None:
    with session_scope() as db:
        drivers, has_next = list_drivers(db, page, active_only=True)
    rows = [
        [
            button(
                f"{driver.name} (#{driver.id})",
                TripCB(action="driver_set", value=str(driver.id)),
            )
        ]
        for driver in drivers
    ]
    nav = []
    if page > 0:
        nav.append(button("Anterior", TripCB(action="driver_page", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TripCB(action="driver_page", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Atrás", TripCB(action="truck_back"))])
    rows.append([button("Cancelar", MenuCB(action="cancel"))])
    await state.set_state(TripCreate.driver)
    text = "<b>Nuevo viaje</b>\n\nElige el conductor."
    if not drivers:
        text = (
            "<b>Nuevo viaje</b>\n\n"
            "No hay conductores activos. Crea un conductor primero."
        )
        rows.insert(0, [button("Crear conductor", MenuCB(action="drivers_new"))])
    await set_ui_message(message, state, text, markup(rows))


async def _begin_create(
    message: Message, state: FSMContext, ui_msg_id: int | None = None
) -> None:
    await state.clear()
    if ui_msg_id:
        await state.update_data(ui_msg_id=ui_msg_id)
    with session_scope() as db:
        trucks = all_active_trucks(db)
        drivers = all_active_drivers(db)
    if not trucks:
        await state.set_state(TripCreate.truck)
        await set_ui_message(
            message,
            state,
            "<b>Nuevo viaje</b>\n\nNo hay camiones activos. Crea un camión primero.",
            markup(
                [
                    [button("Crear camión", MenuCB(action="trucks_new"))],
                    [button("Menú principal", MenuCB(action="main"))],
                ]
            ),
        )
        return
    if not drivers:
        await state.set_state(TripCreate.driver)
        await set_ui_message(
            message,
            state,
            "<b>Nuevo viaje</b>\n\nNo hay conductores activos. Crea un conductor primero.",
            markup(
                [
                    [button("Crear conductor", MenuCB(action="drivers_new"))],
                    [button("Menú principal", MenuCB(action="main"))],
                ]
            ),
        )
        return
    await _show_truck_selection(message, state, 0)


async def _show_list(message: Message, page: int) -> None:
    with session_scope() as db:
        trips, has_next = list_trips(db, page)
        text, keyboard = trips_list_view(trips, page, has_next)
    await edit_or_send(message, text, keyboard)


def _load_trip(trip_id: int) -> Trip | None:
    with session_scope() as db:
        return get_trip(db, trip_id)


async def _show_trip_detail(message: Message, trip_id: int) -> None:
    trip = _load_trip(trip_id)
    if trip is None:
        await edit_or_send(message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_detail_view(trip)
    await edit_or_send(message, text, keyboard)


async def _show_edit_menu(message: Message, state: FSMContext, trip_id: int) -> None:
    trip = _load_trip(trip_id)
    if trip is None:
        await state.clear()
        await edit_or_send(message, "El viaje ya no existe.", markup([]))
        return
    await state.set_state(TripEdit.menu)
    await state.update_data(edit_trip_id=trip.id)
    text = (
        f"<b>Editar viaje #{trip.id}</b>\n\n"
        f"Camión: {trip.truck.name}\n"
        f"Conductor: {trip.driver.name}\n"
        f"Estado: {'Finalizado' if trip.status == TripStatus.finished else 'En curso'}\n"
        f"Fecha: {format_date(trip.trip_date)}\n\n"
        "Elige el campo que quieres modificar."
    )
    fields = [
        ("truck", "Camión"),
        ("driver", "Conductor"),
        ("origin", "Origen"),
        ("destination", "Destino"),
        ("distance", "Millas"),
        ("duration", "Tiempo"),
        ("weight", "Peso"),
        ("percentage", "% Conductor"),
        ("payment", "Pago"),
        ("date", "Fecha"),
        ("status", "Estado"),
        ("notes", "Notas"),
    ]
    rows = []
    current: list = []
    for value, label in fields:
        current.append(button(label, TripCB(action="edit_field", value=value)))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([button("Volver al viaje", TripCB(action="view", trip_id=trip.id))])
    rows.append([button("Menú principal", MenuCB(action="main"))])
    await set_ui_message(message, state, text, markup(rows))


async def _ask_edit_input(
    message: Message,
    state: FSMContext,
    trip_id: int,
    field: str,
    error: str | None = None,
) -> None:
    await state.set_state(TripEdit.input)
    await state.update_data(edit_trip_id=trip_id, edit_field=field)
    text = _field_prompt(field)
    if error:
        text = f"<b>{error}</b>\n\n{text}"
    await set_ui_message(
        message,
        state,
        text,
        markup(
            [
                [
                    button("Atrás", TripCB(action="edit_back")),
                    button("Cancelar", MenuCB(action="cancel")),
                ]
            ]
        ),
    )


async def _show_edit_truck_selection(
    message: Message, state: FSMContext, page: int = 0
) -> None:
    with session_scope() as db:
        trucks, has_next = list_trucks(db, page, active_only=False)
    rows = [
        [
            button(
                f"{truck.name} (#{truck.id})",
                TripCB(action="edit_truck_set", value=str(truck.id)),
            )
        ]
        for truck in trucks
    ]
    nav = []
    if page > 0:
        nav.append(button("Anterior", TripCB(action="edit_truck_page", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TripCB(action="edit_truck_page", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Volver", TripCB(action="edit_back"))])
    await set_ui_message(
        message, state, "<b>Editar camión</b>\n\nElige el camión.", markup(rows)
    )


async def _show_edit_driver_selection(
    message: Message, state: FSMContext, page: int = 0
) -> None:
    with session_scope() as db:
        drivers, has_next = list_drivers(db, page, active_only=False)
    rows = [
        [
            button(
                f"{driver.name} (#{driver.id})",
                TripCB(action="edit_driver_set", value=str(driver.id)),
            )
        ]
        for driver in drivers
    ]
    nav = []
    if page > 0:
        nav.append(button("Anterior", TripCB(action="edit_driver_page", page=page - 1)))
    if has_next:
        nav.append(button("Siguiente", TripCB(action="edit_driver_page", page=page + 1)))
    if nav:
        rows.append(nav)
    rows.append([button("Volver", TripCB(action="edit_back"))])
    await set_ui_message(
        message,
        state,
        "<b>Editar conductor</b>\n\nElige el conductor.",
        markup(rows),
    )


def _apply_edit(trip_id: int, field: str, value) -> Trip | None:
    mapping = {
        "origin": "origin",
        "destination": "destination",
        "distance": "distance_miles",
        "duration": "duration_minutes",
        "weight": "cargo_weight",
        "percentage": "driver_percentage",
        "payment": "cargo_payment",
        "date": "trip_date",
        "status": "status",
        "notes": "notes",
        "truck_id": "truck_id",
        "driver_id": "driver_id",
    }
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            return None
        setattr(trip, mapping[field], value)
        db.flush()
        return get_trip(db, trip.id)


@router.message(Command("viajes"))
async def cmd_trips(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_list(message, 0)


@router.message(Command("nuevoviaje"))
async def cmd_new_trip(message: Message, state: FSMContext) -> None:
    await _begin_create(message, state)


@router.callback_query(MenuCB.filter(F.action == "trips"))
async def cb_trips_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    text, keyboard = trips_menu_view()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(MenuCB.filter(F.action == "trips_list"))
async def cb_trips_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_list(callback.message, 0)


@router.callback_query(MenuCB.filter(F.action == "trip_new"))
async def cb_trip_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _begin_create(callback.message, state, callback.message.message_id)


@router.callback_query(TripCB.filter(F.action == "list"))
async def cb_trip_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await _show_list(callback.message, payload.page)


@router.callback_query(TripCB.filter(F.action == "view"))
async def cb_trip_view(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await _show_trip_detail(callback.message, state, payload.trip_id)


@router.callback_query(TripCB.filter(F.action == "finish"))
async def cb_trip_finish(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    with session_scope() as db:
        trip = get_trip(db, payload.trip_id)
        if trip is not None:
            trip.status = TripStatus.finished
            db.flush()
    await _show_trip_detail(callback.message, state, payload.trip_id)


@router.callback_query(TripCB.filter(F.action == "reopen"))
async def cb_trip_reopen(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    with session_scope() as db:
        trip = get_trip(db, payload.trip_id)
        if trip is not None:
            trip.status = TripStatus.in_progress
            db.flush()
    await _show_trip_detail(callback.message, state, payload.trip_id)


@router.callback_query(TripCB.filter(F.action == "delete"))
async def cb_trip_delete(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    trip = _load_trip(payload.trip_id)
    if trip is None:
        await edit_or_send(callback.message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_delete_confirm_view(trip)
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TripCB.filter(F.action == "delete_confirm"))
async def cb_trip_delete_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    with session_scope() as db:
        trip = get_trip(db, payload.trip_id)
        if trip is not None:
            delete_trip(db, trip)
        trips, has_next = list_trips(db, 0)
    text, keyboard = trips_list_view(trips, 0, has_next)
    await edit_or_send(callback.message, "Viaje eliminado.\n\n" + text, keyboard)


@router.callback_query(TripCB.filter(F.action == "back"))
async def cb_trip_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    current = await state.get_state()
    if current == TripCreate.truck.state:
        await state.clear()
        text, keyboard = trips_menu_view()
        await edit_or_send(callback.message, text, keyboard)
        return
    if current == TripCreate.driver.state:
        await _show_truck_selection(callback.message, state, 0)
        return
    if current == TripCreate.input.state:
        data = await state.get_data()
        field = data.get("current_field")
        if field == "date":
            await _ask_date(callback.message, state)
        elif field in CREATE_FIELDS and CREATE_FIELDS.index(field) > 0:
            await _ask_create_field(
                callback.message, state, CREATE_FIELDS[CREATE_FIELDS.index(field) - 1]
            )
        else:
            await _show_driver_selection(callback.message, state, 0)
        return
    if current == TripCreate.date.state:
        await _ask_create_field(callback.message, state, "payment")
        return
    if current == TripCreate.status.state:
        await _ask_date(callback.message, state)
        return
    if current == TripCreate.notes.state:
        await _ask_status(callback.message, state)
        return
    if current == TripCreate.confirm.state:
        await _ask_notes(callback.message, state)
        return
    if current == TripEdit.input.state:
        data = await state.get_data()
        await _show_edit_menu(callback.message, state, int(data.get("edit_trip_id") or 0))
        return
    if current == TripEdit.menu.state:
        data = await state.get_data()
        await _show_trip_detail(
            callback.message, state, int(data.get("edit_trip_id") or 0)
        )
        return
    await state.clear()
    text, keyboard = trips_menu_view()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TripCB.filter(F.action == "truck_page"))
async def cb_create_truck_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await _show_truck_selection(callback.message, state, payload.page)


@router.callback_query(TripCB.filter(F.action == "truck_back"))
async def cb_create_truck_back(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is not None:
        await _show_truck_selection(callback.message, state, 0)


@router.callback_query(TripCB.filter(F.action == "truck_set"))
async def cb_create_truck_set(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    try:
        truck_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        truck = get_truck(db, truck_id)
    if truck is None or not truck.active:
        await callback.answer("El camión no está disponible.", show_alert=True)
        return
    await state.update_data(truck_id=truck.id, truck_name=truck.name)
    await _show_driver_selection(callback.message, state, 0)


@router.callback_query(TripCB.filter(F.action == "driver_page"))
async def cb_create_driver_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await _show_driver_selection(callback.message, state, payload.page)


@router.callback_query(TripCB.filter(F.action == "driver_set"))
async def cb_create_driver_set(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    try:
        driver_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        driver = get_driver(db, driver_id)
    if driver is None or not driver.active:
        await callback.answer("El conductor no está disponible.", show_alert=True)
        return
    await state.update_data(driver_id=driver.id, driver_name=driver.name)
    await _ask_create_field(callback.message, state, "origin")


@router.callback_query(TripCB.filter(F.action == "date"))
async def cb_create_date(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    today = today_local()
    if payload.value == "today":
        value = today
    elif payload.value == "yesterday":
        value = today - timedelta(days=1)
    elif payload.value == "custom":
        await _ask_create_field(callback.message, state, "date")
        return
    else:
        return
    await state.update_data(trip_date=value.isoformat())
    await _ask_status(callback.message, state)


@router.callback_query(TripCB.filter(F.action == "status"))
async def cb_create_status(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    if payload.value not in (
        TripStatus.in_progress.value,
        TripStatus.finished.value,
    ):
        return
    await state.update_data(status=payload.value)
    await _ask_notes(callback.message, state)


@router.callback_query(TripCB.filter(F.action == "notes_skip"))
async def cb_create_notes_skip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.update_data(notes=None)
    await _show_confirm(callback.message, state)


@router.message(StateFilter(TripCreate.input), F.text)
async def receive_create_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("current_field")
    if field not in CREATE_FIELDS and field != "date":
        return
    value, error = validate_trip_field(field, message.text or "")
    await _delete_user_message(message)
    if error:
        await _ask_create_field(message, state, field, error)
        return

    key = "trip_date" if field == "date" else field
    await state.update_data({key: value.isoformat() if field == "date" else value})
    if field == "payment" or field == "date":
        if field == "date":
            await _ask_status(message, state)
        else:
            await _ask_date(message, state)
        return
    index = CREATE_FIELDS.index(field)
    await _ask_create_field(message, state, CREATE_FIELDS[index + 1])


@router.message(StateFilter(TripCreate.input))
async def receive_create_input_invalid(
    message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    field = data.get("current_field", "origin")
    await _delete_user_message(message)
    await _ask_create_field(
        message, state, field, "Envía el dato como texto."
    )


@router.message(StateFilter(TripCreate.notes), F.text)
async def receive_create_notes(message: Message, state: FSMContext) -> None:
    value, error = validate_trip_field("notes", message.text or "")
    await _delete_user_message(message)
    if error:
        await _ask_notes(message, state)
        return
    await state.update_data(notes=value)
    await _show_confirm(message, state)


@router.message(StateFilter(TripCreate.notes))
async def receive_create_notes_invalid(
    message: Message, state: FSMContext
) -> None:
    await _delete_user_message(message)
    await set_ui_message(
        message,
        state,
        "Envía las notas como texto o pulsa Omitir.",
        notes_kb(),
    )


@router.callback_query(TripCB.filter(F.action == "confirm"))
async def cb_create_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    required = {
        "truck_id",
        "driver_id",
        "origin",
        "destination",
        "distance",
        "duration",
        "weight",
        "percentage",
        "payment",
        "trip_date",
        "status",
    }
    if not required.issubset(data):
        await set_ui_message(
            callback.message,
            state,
            "Faltan datos del viaje. Empieza de nuevo.",
            markup([[button("Menú principal", MenuCB(action="main"))]]),
        )
        await state.clear()
        return
    with session_scope() as db:
        trip = create_trip(
            db,
            truck_id=int(data["truck_id"]),
            driver_id=int(data["driver_id"]),
            status=TripStatus(data["status"]),
            trip_date=date.fromisoformat(data["trip_date"]),
            origin=str(data["origin"]),
            destination=str(data["destination"]),
            distance_miles=Decimal(str(data["distance"])),
            duration_minutes=int(data["duration"]),
            cargo_weight=Decimal(str(data["weight"])),
            driver_percentage=Decimal(str(data["percentage"])),
            cargo_payment=Decimal(str(data["payment"])),
            notes=data.get("notes"),
            created_by=callback.from_user.id,
        )
        trip_id = trip.id
        trip = get_trip(db, trip_id)
        text, keyboard = trip_detail_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.callback_query(TripCB.filter(F.action == "edit"))
async def cb_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await state.clear()
    await state.update_data(ui_msg_id=callback.message.message_id)
    await _show_edit_menu(callback.message, state, payload.trip_id)


@router.callback_query(TripCB.filter(F.action == "edit_field"))
async def cb_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    field = payload.value
    if field == "truck":
        await _show_edit_truck_selection(callback.message, state, trip_id, 0)
    elif field == "driver":
        await _show_edit_driver_selection(callback.message, state, trip_id, 0)
    elif field == "date":
        await state.set_state(TripEdit.menu)
        await set_ui_message(
            callback.message,
            state,
            "Elige la nueva fecha del viaje.",
            edit_date_kb(),
        )
    elif field == "status":
        await state.set_state(TripEdit.menu)
        await set_ui_message(
            callback.message,
            state,
            "Elige el nuevo estado del viaje.",
            edit_status_kb(),
        )
    elif field in EDIT_FIELDS:
        await _ask_edit_input(callback.message, state, trip_id, field)
    else:
        await callback.answer("Campo inválido.", show_alert=True)


@router.callback_query(TripCB.filter(F.action == "edit_back"))
async def cb_edit_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    await _show_edit_menu(callback.message, state, int(data.get("edit_trip_id") or 0))


@router.callback_query(TripCB.filter(F.action == "edit_truck_page"))
async def cb_edit_truck_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    await _show_edit_truck_selection(
        callback.message, state, int(data.get("edit_trip_id") or 0), payload.page
    )


@router.callback_query(TripCB.filter(F.action == "edit_truck_set"))
async def cb_edit_truck_set(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    try:
        truck_id = int(payload.value)
    except ValueError:
        return
    trip = _apply_edit(trip_id, "truck_id", truck_id)
    if trip is None:
        await state.clear()
        await edit_or_send(callback.message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_detail_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.callback_query(TripCB.filter(F.action == "edit_driver_page"))
async def cb_edit_driver_page(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    await _show_edit_driver_selection(
        callback.message, state, int(data.get("edit_trip_id") or 0), payload.page
    )


@router.callback_query(TripCB.filter(F.action == "edit_driver_set"))
async def cb_edit_driver_set(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    try:
        driver_id = int(payload.value)
    except ValueError:
        return
    trip = _apply_edit(trip_id, "driver_id", driver_id)
    if trip is None:
        await state.clear()
        await edit_or_send(callback.message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_detail_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.callback_query(TripCB.filter(F.action == "edit_date"))
async def cb_edit_date(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    today = today_local()
    if payload.value == "today":
        value = today
    elif payload.value == "yesterday":
        value = today - timedelta(days=1)
    elif payload.value == "custom":
        await _ask_edit_input(callback.message, state, trip_id, "date")
        return
    else:
        return
    trip = _apply_edit(trip_id, "date", value)
    if trip is None:
        await state.clear()
        await edit_or_send(callback.message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_detail_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.callback_query(TripCB.filter(F.action == "edit_status"))
async def cb_edit_status(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    if payload.value not in (
        TripStatus.in_progress.value,
        TripStatus.finished.value,
    ):
        return
    trip = _apply_edit(trip_id, "status", TripStatus(payload.value))
    if trip is None:
        await state.clear()
        await edit_or_send(callback.message, "El viaje ya no existe.", markup([]))
        return
    text, keyboard = trip_detail_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.message(StateFilter(TripEdit.input), F.text)
async def receive_edit_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    field = data.get("edit_field")
    if field is None:
        await state.clear()
        return
    value, error = validate_trip_field(field, message.text or "")
    await _delete_user_message(message)
    if error:
        await _ask_edit_input(message, state, trip_id, field, error)
        return

    stored = value
    if field == "duration":
        stored = value
    trip = _apply_edit(trip_id, field, stored)
    if trip is None:
        await set_ui_message(
            message,
            state,
            "El viaje ya no existe.",
            markup([[button("Menú principal", MenuCB(action="main"))]]),
        )
        await state.clear()
        return
    text, keyboard = trip_detail_view(trip)
    await set_ui_message(message, state, text, keyboard)
    await state.clear()


@router.message(StateFilter(TripEdit.input))
async def receive_edit_input_invalid(
    message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    trip_id = int(data.get("edit_trip_id") or 0)
    field = data.get("edit_field", "origin")
    await _delete_user_message(message)
    await _ask_edit_input(
        message, state, trip_id, field, "Envía el dato como texto."
    )
