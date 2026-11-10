from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import MenuCB, TruckCB
from app.database import session_scope
from app.keyboards import button, markup
from app.models import Truck
from app.services.queries import (
    count_trips_for_truck,
    create_truck,
    delete_truck,
    get_truck,
    list_trucks,
    truck_name_exists,
    update_truck,
)
from app.states import TruckForm
from app.ui import edit_or_send, remember_ui_message, set_ui_message
from app.views import truck_detail_view, truck_list_view
from app.keyboards import trucks_menu_kb

router = Router(name="trucks")

NAME_PROMPT = (
    "Escribe el nombre del camión.\n\n"
    "Ejemplo: <code>Unidad 12 - Kenworth</code>"
)


def cancel_kb():
    return markup([[button("Cancelar", MenuCB(action="cancel"))]])


async def _delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def _show_list(message: Message, page: int) -> None:
    with session_scope() as db:
        trucks, has_next = list_trucks(db, page)
        text, keyboard = truck_list_view(trucks, page, has_next)
    await edit_or_send(message, text, keyboard)


def _truck_detail_text(truck: Truck) -> tuple[str, object]:
    with session_scope() as db:
        count = count_trips_for_truck(db, truck.id)
    return truck_detail_view(count, truck)


@router.message(Command("camiones"))
async def cmd_trucks(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_list(message, 0)


@router.message(Command("nuevocamion"))
async def cmd_new_truck(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TruckForm.name)
    await state.update_data(truck_mode="create", truck_id=0)
    await set_ui_message(message, state, NAME_PROMPT, cancel_kb())


@router.callback_query(MenuCB.filter(F.action == "trucks"))
async def cb_trucks_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    await edit_or_send(
        callback.message,
        "<b>Camiones</b>\n\nAdministra el listado de camiones.",
        trucks_menu_kb(),
    )


@router.callback_query(MenuCB.filter(F.action == "trucks_list"))
async def cb_trucks_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_list(callback.message, 0)


@router.callback_query(MenuCB.filter(F.action == "trucks_new"))
async def cb_trucks_new(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await remember_ui_message(callback, state)
    await state.set_state(TruckForm.name)
    await state.update_data(truck_mode="create", truck_id=0)
    if callback.message is not None:
        await set_ui_message(callback.message, state, NAME_PROMPT, cancel_kb())


@router.callback_query(TruckCB.filter(F.action == "list"))
async def cb_truck_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TruckCB.unpack(callback.data)
    await _show_list(callback.message, payload.page)


@router.callback_query(TruckCB.filter(F.action == "view"))
async def cb_truck_view(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TruckCB.unpack(callback.data)
    with session_scope() as db:
        truck = get_truck(db, payload.truck_id)
    if truck is None:
        await edit_or_send(callback.message, "El camión ya no existe.", trucks_menu_kb())
        return
    text, keyboard = _truck_detail_text(truck)
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TruckCB.filter(F.action == "toggle"))
async def cb_truck_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TruckCB.unpack(callback.data)
    with session_scope() as db:
        truck = get_truck(db, payload.truck_id)
        if truck is None:
            text, keyboard = "<b>El camión ya no existe.</b>", trucks_menu_kb()
        else:
            truck.active = not truck.active
            db.flush()
            count = count_trips_for_truck(db, truck.id)
            text, keyboard = truck_detail_view(count, truck)
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TruckCB.filter(F.action == "rename"))
async def cb_truck_rename(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TruckCB.unpack(callback.data)
    await state.clear()
    await state.update_data(ui_msg_id=callback.message.message_id)
    await state.set_state(TruckForm.name)
    await state.update_data(truck_mode="edit", truck_id=payload.truck_id)
    await set_ui_message(
        callback.message,
        state,
        "Escribe el nuevo nombre del camión.",
        cancel_kb(),
    )


@router.callback_query(TruckCB.filter(F.action == "delete"))
async def cb_truck_delete(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    payload = TruckCB.unpack(callback.data)
    with session_scope() as db:
        truck = get_truck(db, payload.truck_id)
        if truck is None:
            text, keyboard = "<b>El camión ya no existe.</b>", trucks_menu_kb()
        else:
            count = count_trips_for_truck(db, truck.id)
            if count:
                await callback.answer(
                    "El camión tiene viajes asociados. Desactívalo en su lugar.",
                    show_alert=True,
                )
                return
            text = (
                f"<b>Eliminar {truck.name}</b>\n\n"
                "Esta acción no se puede deshacer."
            )
            keyboard = markup(
                [
                    [
                        button(
                            "Sí, eliminar",
                            TruckCB(action="delete_confirm", truck_id=truck.id),
                        )
                    ],
                    [button("Cancelar", TruckCB(action="view", truck_id=truck.id))],
                ]
            )
    await callback.answer()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TruckCB.filter(F.action == "delete_confirm"))
async def cb_truck_delete_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TruckCB.unpack(callback.data)
    with session_scope() as db:
        truck = get_truck(db, payload.truck_id)
        if truck is not None and count_trips_for_truck(db, truck.id) == 0:
            delete_truck(db, truck)
        trucks, has_next = list_trucks(db, 0)
    text, keyboard = truck_list_view(trucks, 0, has_next)
    await edit_or_send(callback.message, "Camión eliminado.\n\n" + text, keyboard)


@router.message(StateFilter(TruckForm.name), F.text)
async def receive_truck_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    data = await state.get_data()
    mode = data.get("truck_mode", "create")
    truck_id = int(data.get("truck_id") or 0)
    await _delete_user_message(message)

    if not name:
        await set_ui_message(
            message,
            state,
            "El nombre no puede estar vacío.\n\n" + NAME_PROMPT,
            cancel_kb(),
        )
        return
    if len(name) > 120:
        await set_ui_message(
            message,
            state,
            "El nombre es demasiado largo (máximo 120 caracteres).",
            cancel_kb(),
        )
        return

    with session_scope() as db:
        if truck_name_exists(db, name, exclude_id=truck_id or None):
            await set_ui_message(
                message,
                state,
                "Ya existe un camión con ese nombre. Prueba con otro.",
                cancel_kb(),
            )
            return
        if mode == "edit":
            truck = get_truck(db, truck_id)
            if truck is None:
                await set_ui_message(
                    message, state, "El camión ya no existe.", trucks_menu_kb()
                )
                await state.clear()
                return
            update_truck(db, truck, name=name)
        else:
            truck = create_truck(db, name)
        count = count_trips_for_truck(db, truck.id)
        text, keyboard = truck_detail_view(count, truck)

    await set_ui_message(message, state, text, keyboard)
    await state.clear()


@router.message(StateFilter(TruckForm.name))
async def receive_truck_name_invalid(
    message: Message, state: FSMContext
) -> None:
    await _delete_user_message(message)
    await set_ui_message(
        message,
        state,
        "Envía el nombre del camión como texto.\n\n" + NAME_PROMPT,
        cancel_kb(),
    )
