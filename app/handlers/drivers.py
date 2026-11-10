from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import DriverCB, MenuCB
from app.database import session_scope
from app.keyboards import button, drivers_menu_kb, markup
from app.models import Driver
from app.services.queries import (
    count_trips_for_driver,
    create_driver,
    delete_driver,
    get_driver,
    list_drivers,
    update_driver,
)
from app.states import DriverForm
from app.ui import edit_or_send, remember_ui_message, set_ui_message
from app.views import driver_detail_view, driver_list_view

router = Router(name="drivers")

PHONE_RE = re.compile(r"^[0-9+()\-\s.]+$")
NAME_PROMPT = (
    "Escribe el nombre del conductor.\n\n"
    "Ejemplo: <code>Juan Pérez</code>"
)
PHONE_PROMPT = (
    "Escribe el teléfono del conductor o pulsa <b>Omitir</b>."
)


def cancel_kb():
    return markup([[button("Cancelar", MenuCB(action="cancel"))]])


def skip_kb():
    return markup(
        [
            [button("Omitir", DriverCB(action="phone_skip"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


async def _delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _show_list(message: Message, page: int) -> None:
    with session_scope() as db:
        drivers, has_next = list_drivers(db, page)
        text, keyboard = driver_list_view(drivers, page, has_next)
    await edit_or_send(message, text, keyboard)


def _detail(driver: Driver) -> tuple[str, object]:
    with session_scope() as db:
        count = count_trips_for_driver(db, driver.id)
    return driver_detail_view(count, driver)


async def _prompt_name(message: Message, state: FSMContext, mode: str, driver_id: int = 0) -> None:
    await state.set_state(DriverForm.name)
    await state.update_data(driver_mode=mode, driver_id=driver_id)
    await set_ui_message(message, state, NAME_PROMPT, cancel_kb())


@router.message(Command("conductores"))
async def cmd_drivers(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_list(message, 0)


@router.message(Command("nuevoconductor"))
async def cmd_new_driver(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _prompt_name(message, state, "create")


@router.callback_query(MenuCB.filter(F.action == "drivers"))
async def cb_drivers_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    await edit_or_send(
        callback.message,
        "<b>Conductores</b>\n\nAdministra el listado de conductores.",
        drivers_menu_kb(),
    )


@router.callback_query(MenuCB.filter(F.action == "drivers_list"))
async def cb_drivers_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_list(callback.message, 0)


@router.callback_query(MenuCB.filter(F.action == "drivers_new"))
async def cb_drivers_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await remember_ui_message(callback, state)
    if callback.message is not None:
        await _prompt_name(callback.message, state, "create")


@router.callback_query(DriverCB.filter(F.action == "list"))
async def cb_driver_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    await _show_list(callback.message, payload.page)


@router.callback_query(DriverCB.filter(F.action == "view"))
async def cb_driver_view(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    with session_scope() as db:
        driver = get_driver(db, payload.driver_id)
    if driver is None:
        await edit_or_send(
            callback.message, "El conductor ya no existe.", drivers_menu_kb()
        )
        return
    text, keyboard = _detail(driver)
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(DriverCB.filter(F.action == "toggle"))
async def cb_driver_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    with session_scope() as db:
        driver = get_driver(db, payload.driver_id)
        if driver is None:
            text, keyboard = "<b>El conductor ya no existe.</b>", drivers_menu_kb()
        else:
            driver.active = not driver.active
            db.flush()
            count = count_trips_for_driver(db, driver.id)
            text, keyboard = driver_detail_view(count, driver)
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(DriverCB.filter(F.action == "rename"))
async def cb_driver_rename(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    await state.clear()
    await state.update_data(ui_msg_id=callback.message.message_id)
    await _prompt_name(callback.message, state, "edit", payload.driver_id)


@router.callback_query(DriverCB.filter(F.action == "phone"))
async def cb_driver_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    await state.clear()
    await state.update_data(ui_msg_id=callback.message.message_id)
    await state.set_state(DriverForm.phone)
    await state.update_data(driver_mode="edit_phone", driver_id=payload.driver_id)
    await set_ui_message(callback.message, state, PHONE_PROMPT, skip_kb())


@router.callback_query(DriverCB.filter(F.action == "delete"))
async def cb_driver_delete(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    payload = DriverCB.unpack(callback.data)
    with session_scope() as db:
        driver = get_driver(db, payload.driver_id)
        if driver is None:
            text, keyboard = "<b>El conductor ya no existe.</b>", drivers_menu_kb()
        else:
            count = count_trips_for_driver(db, driver.id)
            if count:
                await callback.answer(
                    "El conductor tiene viajes asociados. Desactívalo en su lugar.",
                    show_alert=True,
                )
                return
            text = (
                f"<b>Eliminar {driver.name}</b>\n\n"
                "Esta acción no se puede deshacer."
            )
            keyboard = markup(
                [
                    [
                        button(
                            "Sí, eliminar",
                            DriverCB(
                                action="delete_confirm", driver_id=driver.id
                            ),
                        )
                    ],
                    [
                        button(
                            "Cancelar",
                            DriverCB(action="view", driver_id=driver.id),
                        )
                    ],
                ]
            )
    await callback.answer()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(DriverCB.filter(F.action == "delete_confirm"))
async def cb_driver_delete_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = DriverCB.unpack(callback.data)
    with session_scope() as db:
        driver = get_driver(db, payload.driver_id)
        if driver is not None and count_trips_for_driver(db, driver.id) == 0:
            delete_driver(db, driver)
        drivers, has_next = list_drivers(db, 0)
    text, keyboard = driver_list_view(drivers, 0, has_next)
    await edit_or_send(callback.message, "Conductor eliminado.\n\n" + text, keyboard)


@router.message(StateFilter(DriverForm.name), F.text)
async def receive_driver_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    data = await state.get_data()
    mode = data.get("driver_mode", "create")
    driver_id = int(data.get("driver_id") or 0)
    await _delete_user_message(message)

    if not name or len(name) > 120:
        await set_ui_message(
            message,
            state,
            "El nombre debe tener entre 1 y 120 caracteres.\n\n" + NAME_PROMPT,
            cancel_kb(),
        )
        return

    if mode == "edit":
        with session_scope() as db:
            driver = get_driver(db, driver_id)
            if driver is None:
                await set_ui_message(
                    message, state, "El conductor ya no existe.", drivers_menu_kb()
                )
                await state.clear()
                return
            update_driver(db, driver, name=name)
            count = count_trips_for_driver(db, driver.id)
            text, keyboard = driver_detail_view(count, driver)
        await set_ui_message(message, state, text, keyboard)
        await state.clear()
        return

    await state.update_data(driver_name=name)
    await state.set_state(DriverForm.phone)
    await set_ui_message(message, state, PHONE_PROMPT, skip_kb())


@router.message(StateFilter(DriverForm.name))
async def receive_driver_name_invalid(
    message: Message, state: FSMContext
) -> None:
    await _delete_user_message(message)
    await set_ui_message(
        message,
        state,
        "Envía el nombre del conductor como texto.\n\n" + NAME_PROMPT,
        cancel_kb(),
    )


@router.message(StateFilter(DriverForm.phone), F.text)
async def receive_driver_phone(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    await _delete_user_message(message)
    if raw and (len(raw) > 40 or not PHONE_RE.fullmatch(raw)):
        await set_ui_message(
            message,
            state,
            "Teléfono inválido. Usa números, espacios, +, paréntesis o guiones.",
            skip_kb(),
        )
        return
    await _finish_phone(message, state, raw or None)


@router.message(StateFilter(DriverForm.phone))
async def receive_driver_phone_invalid(
    message: Message, state: FSMContext
) -> None:
    await _delete_user_message(message)
    await set_ui_message(
        message,
        state,
        "Envía el teléfono como texto o pulsa Omitir.",
        skip_kb(),
    )


@router.callback_query(DriverCB.filter(F.action == "phone_skip"))
async def cb_driver_phone_skip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _finish_phone(callback.message, state, None)


async def _finish_phone(
    message: Message, state: FSMContext, phone: str | None
) -> None:
    data = await state.get_data()
    mode = data.get("driver_mode", "create")
    driver_id = int(data.get("driver_id") or 0)

    with session_scope() as db:
        if mode == "create":
            name = str(data.get("driver_name") or "").strip()
            if not name:
                await set_ui_message(
                    message, state, "Falta el nombre. Empecemos otra vez.", cancel_kb()
                )
                return
            driver = create_driver(db, name, phone)
        else:
            driver = get_driver(db, driver_id)
            if driver is None:
                await set_ui_message(
                    message, state, "El conductor ya no existe.", drivers_menu_kb()
                )
                await state.clear()
                return
            update_driver(db, driver, phone=phone)

        count = count_trips_for_driver(db, driver.id)
        text, keyboard = driver_detail_view(count, driver)

    await set_ui_message(message, state, text, keyboard)
    await state.clear()
