from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import MenuCB, SettingsCB
from app.database import session_scope
from app.keyboards import button, cancel_row, markup
from app.services.queries import (
    get_bot_settings,
    get_truck,
    list_trucks,
    update_bot_settings,
)
from app.services.reports import send_week_report
from app.services.scheduler import notify_report_scheduler
from app.services.weeks import current_week_bounds, parse_time_text
from app.states import SettingsFlow
from app.ui import edit_or_send, set_ui_message
from app.views import (
    day_menu_kb,
    scope_menu_kb,
    settings_truck_list_view,
    settings_view,
    time_menu_kb,
)

router = Router(name="settings")


def _settings_content() -> tuple[str, object]:
    with session_scope() as db:
        config = get_bot_settings(db)
        truck = (
            get_truck(db, config.report_truck_id)
            if config.report_scope == "truck" and config.report_truck_id
            else None
        )
        truck_name = truck.name if truck is not None else None
        text, keyboard = settings_view(config, truck_name)
    return text, keyboard


async def _show_settings(message: Message) -> None:
    text, keyboard = _settings_content()
    await edit_or_send(message, text, keyboard)


def _time_prompt_kb() -> object:
    return markup(
        [
            [button("Volver", SettingsCB(action="show"))],
            cancel_row(),
        ]
    )


@router.message(Command("configuracion"))
async def cmd_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_settings(message)


@router.callback_query(MenuCB.filter(F.action == "settings"))
async def cb_settings_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "show"))
async def cb_settings_show(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "day_menu"))
async def cb_settings_day_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is not None:
        await edit_or_send(
            callback.message,
            "<b>Día del reporte</b>\n\nElige el día de la semana.",
            day_menu_kb(),
        )


@router.callback_query(SettingsCB.filter(F.action == "day"))
async def cb_settings_day(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.data is None:
        return
    payload = SettingsCB.unpack(callback.data)
    try:
        day = int(payload.value)
    except ValueError:
        return
    if not 0 <= day <= 6:
        return
    with session_scope() as db:
        update_bot_settings(db, report_day=day)
    notify_report_scheduler()
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "time_menu"))
async def cb_settings_time_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is not None:
        await edit_or_send(
            callback.message,
            "<b>Hora del reporte</b>\n\nElige una hora.",
            time_menu_kb(),
        )


@router.callback_query(SettingsCB.filter(F.action == "time"))
async def cb_settings_time(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.data is None:
        return
    payload = SettingsCB.unpack(callback.data)
    parsed = parse_time_text(payload.value)
    if parsed is None:
        return
    text = f"{parsed[0]:02d}:{parsed[1]:02d}"
    with session_scope() as db:
        update_bot_settings(db, report_time=text)
    notify_report_scheduler()
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "time_custom"))
async def cb_settings_time_custom(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(SettingsFlow.time)
    await set_ui_message(
        callback.message,
        state,
        (
            "<b>Otra hora</b>\n\n"
            "Escribe la hora en formato <code>HH:MM</code> "
            "(por ejemplo <code>07:30</code>)."
        ),
        _time_prompt_kb(),
    )


@router.callback_query(SettingsCB.filter(F.action == "scope_menu"))
async def cb_settings_scope_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is not None:
        await edit_or_send(
            callback.message,
            "<b>Alcance del reporte</b>\n\nElige el alcance.",
            scope_menu_kb(),
        )


@router.callback_query(SettingsCB.filter(F.action == "scope"))
async def cb_settings_scope(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = SettingsCB.unpack(callback.data)
    if payload.value == "general":
        with session_scope() as db:
            update_bot_settings(
                db, report_scope="general", report_truck_id=None
            )
        notify_report_scheduler()
        await _show_settings(callback.message)
        return
    await _show_scope_truck_list(callback.message, 0)


async def _show_scope_truck_list(message: Message, page: int) -> None:
    with session_scope() as db:
        trucks, has_next = list_trucks(db, page)
        text, keyboard = settings_truck_list_view(trucks, page, has_next)
    await edit_or_send(message, text, keyboard)


@router.callback_query(SettingsCB.filter(F.action == "scope_truck"))
async def cb_settings_scope_truck(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = SettingsCB.unpack(callback.data)
    await _show_scope_truck_list(callback.message, payload.page)


@router.callback_query(SettingsCB.filter(F.action == "truck"))
async def cb_settings_truck(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = SettingsCB.unpack(callback.data)
    try:
        truck_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        truck = get_truck(db, truck_id)
        if truck is None:
            await _show_scope_truck_list(callback.message, 0)
            return
        update_bot_settings(
            db, report_scope="truck", report_truck_id=truck.id
        )
    notify_report_scheduler()
    await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "toggle"))
async def cb_settings_toggle(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    with session_scope() as db:
        config = get_bot_settings(db)
        update_bot_settings(
            db, report_enabled=not config.report_enabled
        )
    notify_report_scheduler()
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "chat"))
async def cb_settings_chat(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    with session_scope() as db:
        update_bot_settings(db, report_chat_id=callback.message.chat.id)
    if callback.message is not None:
        await _show_settings(callback.message)


@router.callback_query(SettingsCB.filter(F.action == "test"))
async def cb_settings_test(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.answer("Generando reporte de prueba...")
    with session_scope() as db:
        config = get_bot_settings(db)
        scope = config.report_scope or "general"
        truck_id = config.report_truck_id or 0
    start, end = current_week_bounds()
    await send_week_report(
        callback.bot,
        callback.message.chat.id,
        start,
        end,
        scope=scope,
        truck_id=truck_id,
    )


@router.message(StateFilter(SettingsFlow.time))
async def receive_settings_time(
    message: Message, state: FSMContext
) -> None:
    parsed = parse_time_text(message.text or "")
    if parsed is None:
        await set_ui_message(
            message,
            state,
            (
                "<b>Otra hora</b>\n\n"
                "La hora no es válida. Usa el formato <code>HH:MM</code>."
            ),
            _time_prompt_kb(),
        )
        return
    text = f"{parsed[0]:02d}:{parsed[1]:02d}"
    with session_scope() as db:
        update_bot_settings(db, report_time=text)
    notify_report_scheduler()
    view_text, keyboard = _settings_content()
    await set_ui_message(message, state, view_text, keyboard)
    await state.clear()
