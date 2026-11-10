from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InputMediaDocument,
    InputMediaPhoto,
    Message,
)

from app.callbacks import MenuCB, TicketCB, TripCB
from app.database import session_scope
from app.keyboards import button, markup, tickets_menu_kb
from app.models import Ticket, TicketKind, TicketMedia
from app.services.queries import add_ticket, get_trip, list_tickets, list_trips
from app.states import TicketFlow
from app.ui import edit_or_send, remember_ui_message, set_ui_message
from app.utils import kind_label
from app.views import ticket_add_kb, ticket_menu_view, ticket_trip_list_view

router = Router(name="tickets")


def done_kb() -> object:
    return markup(
        [
            [button("Listo", TicketCB(action="done"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


async def _show_trip_list(message: Message, page: int) -> None:
    with session_scope() as db:
        trips, has_next = list_trips(db, page)
        text, keyboard = ticket_trip_list_view(trips, page, has_next)
    await edit_or_send(message, text, keyboard)


async def _show_ticket_menu(message: Message, trip_id: int) -> None:
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            await edit_or_send(message, "El viaje ya no existe.", tickets_menu_kb())
            return
        text, keyboard = ticket_menu_view(trip)
    await edit_or_send(message, text, keyboard)


async def _send_tickets(bot: Bot, chat_id: int, tickets: list[Ticket]) -> int:
    if not tickets:
        return 0
    photos = [
        ticket for ticket in tickets if ticket.media_type == TicketMedia.photo
    ]
    documents = [
        ticket for ticket in tickets if ticket.media_type == TicketMedia.document
    ]
    for start in range(0, len(photos), 10):
        chunk = photos[start : start + 10]
        await bot.send_media_group(
            chat_id=chat_id,
            media=[InputMediaPhoto(media=ticket.telegram_file_id) for ticket in chunk],
        )
    for start in range(0, len(documents), 10):
        chunk = documents[start : start + 10]
        await bot.send_media_group(
            chat_id=chat_id,
            media=[
                InputMediaDocument(media=ticket.telegram_file_id) for ticket in chunk
            ],
        )
    return len(tickets)


@router.message(Command("tickets"))
async def cmd_tickets(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_trip_list(message, 0)


@router.callback_query(MenuCB.filter(F.action == "tickets"))
async def cb_tickets_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    await edit_or_send(
        callback.message,
        "<b>Tickets</b>\n\nElige un viaje para administrar sus imágenes.",
        tickets_menu_kb(),
    )


@router.callback_query(MenuCB.filter(F.action == "tickets_list"))
async def cb_tickets_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_trip_list(callback.message, 0)


@router.callback_query(TicketCB.filter(F.action == "list"))
async def cb_ticket_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    await _show_trip_list(callback.message, payload.page)


@router.callback_query(TicketCB.filter(F.action == "menu"))
async def cb_ticket_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    await _show_ticket_menu(callback.message, payload.trip_id)


@router.callback_query(TripCB.filter(F.action == "ticket_menu"))
async def cb_ticket_menu_from_trip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TripCB.unpack(callback.data)
    await _show_ticket_menu(callback.message, payload.trip_id)


@router.callback_query(TicketCB.filter(F.action == "add"))
async def cb_ticket_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    await edit_or_send(
        callback.message,
        "<b>Agregar tickets</b>\n\nElige la categoría de las imágenes.",
        ticket_add_kb(payload.trip_id),
    )


@router.callback_query(TicketCB.filter(F.action == "kind"))
async def cb_ticket_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    try:
        kind = TicketKind(payload.value)
    except ValueError:
        return
    await state.clear()
    await remember_ui_message(callback, state)
    await state.set_state(TicketFlow.media)
    await state.update_data(ticket_trip_id=payload.trip_id, ticket_kind=kind.value)
    with session_scope() as db:
        trip = get_trip(db, payload.trip_id)
        count = len(trip.tickets) if trip else 0
    await set_ui_message(
        callback.message,
        state,
        (
            f"<b>Tickets de {kind_label(kind).lower()}</b>\n\n"
            f"Envía una o varias imágenes. Ya hay {count} tickets en el viaje.\n"
            "Cuando termines pulsa <b>Listo</b>."
        ),
        done_kb(),
    )


@router.callback_query(TicketCB.filter(F.action == "done"))
async def cb_ticket_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    trip_id = int(data.get("ticket_trip_id") or 0)
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            await set_ui_message(
                callback.message,
                state,
                "El viaje ya no existe.",
                tickets_menu_kb(),
            )
            await state.clear()
            return
        text, keyboard = ticket_menu_view(trip)
    await set_ui_message(callback.message, state, text, keyboard)
    await state.clear()


@router.callback_query(TicketCB.filter(F.action == "resend_all"))
async def cb_ticket_resend_all(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    payload = TicketCB.unpack(callback.data)
    with session_scope() as db:
        tickets = list_tickets(db, payload.trip_id)
    if not tickets:
        await callback.answer("No hay tickets para reenviar.", show_alert=True)
        return
    total = await _send_tickets(callback.bot, callback.message.chat.id, tickets)
    await callback.answer(f"Reenviando {total} tickets.")


@router.callback_query(TicketCB.filter(F.action == "resend_kind"))
async def cb_ticket_resend_kind(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    payload = TicketCB.unpack(callback.data)
    try:
        kind = TicketKind(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        tickets = [
            ticket
            for ticket in list_tickets(db, payload.trip_id)
            if ticket.kind == kind
        ]
    if not tickets:
        await callback.answer("No hay tickets de esa categoría.", show_alert=True)
        return
    total = await _send_tickets(callback.bot, callback.message.chat.id, tickets)
    await callback.answer(f"Reenviando {total} tickets.")


@router.message(StateFilter(TicketFlow.media), F.photo)
async def receive_ticket_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    trip_id = int(data.get("ticket_trip_id") or 0)
    kind = TicketKind(data.get("ticket_kind", TicketKind.other.value))
    photo = message.photo[-1]
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            await state.clear()
            await message.answer("El viaje ya no existe.")
            return
        _, created = add_ticket(
            db,
            trip_id=trip_id,
            kind=kind,
            media_type=TicketMedia.photo,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            caption=message.caption,
            width=photo.width,
            height=photo.height,
            uploaded_by=message.from_user.id,
        )
        count = len(list_tickets(db, trip_id))
    if not created:
        await message.answer("Esa imagen ya estaba agregada al viaje.")
        return
    await set_ui_message(
        message,
        state,
        (
            f"<b>Tickets de {kind_label(kind).lower()}</b>\n\n"
            f"Imágenes guardadas. El viaje tiene {count} tickets.\n"
            "Envía otra imagen o pulsa <b>Listo</b>."
        ),
        done_kb(),
    )


@router.message(StateFilter(TicketFlow.media), F.document)
async def receive_ticket_document(message: Message, state: FSMContext) -> None:
    document = message.document
    if document is None or not (document.mime_type or "").startswith("image/"):
        await message.answer("Solo se aceptan imágenes.")
        return
    data = await state.get_data()
    trip_id = int(data.get("ticket_trip_id") or 0)
    kind = TicketKind(data.get("ticket_kind", TicketKind.other.value))
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            await state.clear()
            await message.answer("El viaje ya no existe.")
            return
        _, created = add_ticket(
            db,
            trip_id=trip_id,
            kind=kind,
            media_type=TicketMedia.document,
            file_id=document.file_id,
            file_unique_id=document.file_unique_id,
            caption=message.caption,
            width=None,
            height=None,
            uploaded_by=message.from_user.id,
        )
        count = len(list_tickets(db, trip_id))
    if not created:
        await message.answer("Esa imagen ya estaba agregada al viaje.")
        return
    await set_ui_message(
        message,
        state,
        (
            f"<b>Tickets de {kind_label(kind).lower()}</b>\n\n"
            f"Imágenes guardadas. El viaje tiene {count} tickets.\n"
            "Envía otra imagen o pulsa <b>Listo</b>."
        ),
        done_kb(),
    )


@router.message(StateFilter(TicketFlow.media))
async def receive_ticket_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Envía imágenes o pulsa Listo para terminar.")
