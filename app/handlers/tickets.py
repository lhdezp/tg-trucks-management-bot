from __future__ import annotations

import logging
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
    Message,
)

from app.callbacks import MenuCB, TicketCB, TripCB
from app.config import get_settings
from app.database import session_scope
from app.keyboards import button, markup, tickets_menu_kb
from app.models import Ticket, TicketKind, TicketMedia, Trip, utcnow_naive
from app.services import ticket_ai
from app.services.queries import (
    PAGE_SIZE,
    add_ticket,
    get_ticket,
    get_trip,
    list_tickets,
    list_trips,
    update_ticket_amount,
)
from app.states import TicketFlow
from app.ui import edit_or_send, remember_ui_message, set_ui_message
from app.utils import format_money, kind_label, parse_decimal
from app.views import (
    ticket_add_kb,
    ticket_amount_prompt_view,
    ticket_amounts_view,
    ticket_menu_view,
    ticket_trip_list_view,
)

router = Router(name="tickets")
logger = logging.getLogger(__name__)


def done_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Listo", TicketCB(action="done"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def _saved_kb(
    trip_id: int, ticket_id: int, amount: Decimal | None
) -> InlineKeyboardMarkup:
    rows: list[list] = []
    if amount is None:
        rows.append(
            [
                button(
                    "Insertar monto manual",
                    TicketCB(
                        action="amount_edit",
                        trip_id=trip_id,
                        value=str(ticket_id),
                    ),
                )
            ]
        )
    else:
        rows.append(
            [
                button(
                    "Si, es correcto",
                    TicketCB(
                        action="amount_confirm",
                        trip_id=trip_id,
                        value=str(ticket_id),
                    ),
                )
            ]
        )
        rows.append(
            [
                button(
                    "Corregir monto",
                    TicketCB(
                        action="amount_edit",
                        trip_id=trip_id,
                        value=str(ticket_id),
                    ),
                )
            ]
        )
    rows.append([button("Listo", TicketCB(action="done"))])
    rows.append([button("Cancelar", MenuCB(action="cancel"))])
    return markup(rows)


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


def _amounts_view(
    trip_id: int, page: int
) -> tuple[str, InlineKeyboardMarkup] | None:
    with session_scope() as db:
        trip = get_trip(db, trip_id)
        if trip is None:
            return None
        tickets = list_tickets(db, trip_id)
        start = page * PAGE_SIZE
        page_tickets = tickets[start : start + PAGE_SIZE]
        has_next = len(tickets) > start + PAGE_SIZE
        return ticket_amounts_view(trip, page_tickets, page, has_next)


def _saved_text(
    trip: Trip,
    kind: TicketKind,
    count: int,
    amount: Decimal | None = None,
    error: str | None = None,
) -> str:
    settings = get_settings()
    lines = [
        f"<b>Tickets de {kind_label(kind).lower()}</b>",
        "",
        f"Imagenes guardadas. El viaje tiene {count} tickets.",
    ]
    if amount is not None:
        lines.append(
            f"Monto detectado: {format_money(amount, settings.currency)} "
            "(sin confirmar)"
        )
        lines.append(
            "Confirma que el monto es correcto o corregilo antes de continuar."
        )
    elif error:
        lines.append(error)
        lines.append("Podes insertar el monto manualmente con el boton de abajo.")
    lines.append(
        f"Gastos confirmados del viaje: "
        f"{format_money(trip.ticket_expenses, settings.currency)}"
    )
    if trip.tickets_without_amount:
        lines.append(f"Tickets sin monto: {trip.tickets_without_amount}")
    if trip.tickets_pending_confirmation:
        lines.append(
            f"Tickets sin confirmar: {trip.tickets_pending_confirmation}"
        )
    lines.append("Envia otra imagen o pulsa <b>Listo</b>.")
    return "\n".join(lines)


async def _finish_ticket_analysis(
    message: Message,
    state: FSMContext,
    *,
    trip_id: int,
    kind: TicketKind,
    ticket_id: int,
    amount: Decimal | None,
    error: str | None,
) -> None:
    with session_scope() as db:
        if amount is not None:
            ticket = get_ticket(db, ticket_id)
            if ticket is not None:
                update_ticket_amount(
                    db,
                    ticket,
                    amount=amount,
                    source="ai_pending",
                    ai_model=get_settings().gemini_model,
                    processed_at=utcnow_naive(),
                )
        trip = get_trip(db, trip_id)
        if trip is None:
            await set_ui_message(
                message,
                state,
                "El viaje ya no existe.",
                tickets_menu_kb(),
            )
            return
        text = _saved_text(trip, kind, len(trip.tickets), amount, error)
    if await state.get_state() != TicketFlow.media.state:
        settings = get_settings()
        if amount is not None:
            notice = (
                f"Monto detectado: {format_money(amount, settings.currency)}\n"
                f"Gastos del viaje: "
                f"{format_money(trip.ticket_expenses, settings.currency)}"
            )
        else:
            notice = error or "No se pudo detectar el monto automaticamente."
        await message.answer(notice)
        return
    await set_ui_message(
        message, state, text, _saved_kb(trip_id, ticket_id, amount)
    )


async def _analyze_ticket(
    message: Message,
    state: FSMContext,
    *,
    trip_id: int,
    kind: TicketKind,
    ticket_id: int,
    file_id: str,
    file_size: int | None,
    mime_type: str,
) -> None:
    if not ticket_ai.is_enabled():
        await _finish_ticket_analysis(
            message,
            state,
            trip_id=trip_id,
            kind=kind,
            ticket_id=ticket_id,
            amount=None,
            error="El analisis automatico de montos no esta configurado.",
        )
        return

    await set_ui_message(
        message,
        state,
        "<b>Analizando monto del ticket...</b>\n\nEsto puede demorar unos segundos.",
        done_kb(),
    )
    image = await ticket_ai.download_image(message.bot, file_id, file_size)
    if image is None:
        await _finish_ticket_analysis(
            message,
            state,
            trip_id=trip_id,
            kind=kind,
            ticket_id=ticket_id,
            amount=None,
            error="No se pudo descargar la imagen para analizarla.",
        )
        return

    result = await ticket_ai.extract_ticket_amount(image, mime_type)
    amount = None
    if result is not None:
        amount = Decimal(str(result.amount)).quantize(Decimal("0.01"))
    await _finish_ticket_analysis(
        message,
        state,
        trip_id=trip_id,
        kind=kind,
        ticket_id=ticket_id,
        amount=amount,
        error=(
            None
            if amount is not None
            else "No se pudo detectar el monto automaticamente."
        ),
    )


async def _send_ticket_group(
    bot: Bot, chat_id: int, tickets: list[Ticket]
) -> int:
    if not tickets:
        return 0
    grouped = [
        (
            InputMediaPhoto(media=ticket.telegram_file_id)
            if ticket.media_type == TicketMedia.photo
            else InputMediaDocument(media=ticket.telegram_file_id)
        )
        for ticket in tickets
    ]
    try:
        await bot.send_media_group(chat_id=chat_id, media=grouped)
        return len(tickets)
    except Exception:
        logger.exception(
            "No se pudo reenviar un grupo de tickets; se intentará uno por uno"
        )
    sent = 0
    for ticket in tickets:
        try:
            if ticket.media_type == TicketMedia.photo:
                await bot.send_photo(chat_id, ticket.telegram_file_id)
            else:
                await bot.send_document(chat_id, ticket.telegram_file_id)
            sent += 1
        except Exception:
            logger.exception(
                "No se pudo reenviar el ticket %s del viaje %s",
                ticket.id,
                ticket.trip_id,
            )
    return sent


async def _send_tickets(bot: Bot, chat_id: int, tickets: list[Ticket]) -> int:
    if not tickets:
        return 0
    photos = [
        ticket for ticket in tickets if ticket.media_type == TicketMedia.photo
    ]
    documents = [
        ticket for ticket in tickets if ticket.media_type == TicketMedia.document
    ]
    sent = 0
    for start in range(0, len(photos), 10):
        sent += await _send_ticket_group(
            bot, chat_id, photos[start : start + 10]
        )
    for start in range(0, len(documents), 10):
        sent += await _send_ticket_group(
            bot, chat_id, documents[start : start + 10]
        )
    return sent


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


@router.callback_query(TicketCB.filter(F.action == "amounts"))
async def cb_ticket_amounts(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    view = _amounts_view(payload.trip_id, payload.page)
    if view is None:
        await edit_or_send(
            callback.message,
            "El viaje ya no existe.",
            tickets_menu_kb(),
        )
        return
    text, keyboard = view
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TicketCB.filter(F.action == "amount_edit"))
async def cb_ticket_amount_edit(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    try:
        ticket_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await edit_or_send(
                callback.message,
                "El ticket ya no existe.",
                tickets_menu_kb(),
            )
            return
        ticket_trip_id = ticket.trip_id
        text, keyboard = ticket_amount_prompt_view(ticket)
    if ticket_trip_id != payload.trip_id:
        return
    await state.clear()
    await remember_ui_message(callback, state)
    await state.set_state(TicketFlow.amount)
    await state.update_data(
        ticket_id=ticket_id,
        ticket_trip_id=ticket_trip_id,
    )
    await set_ui_message(callback.message, state, text, keyboard)


@router.callback_query(TicketCB.filter(F.action == "amount_clear"))
async def cb_ticket_amount_clear(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    try:
        ticket_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await edit_or_send(
                callback.message,
                "El ticket ya no existe.",
                tickets_menu_kb(),
            )
            return
        update_ticket_amount(
            db,
            ticket,
            amount=None,
            source=None,
            ai_model=None,
            processed_at=None,
        )
        ticket_trip_id = ticket.trip_id
        text, keyboard = ticket_amount_prompt_view(
            ticket, note="Monto eliminado."
        )
    await state.clear()
    await remember_ui_message(callback, state)
    await state.set_state(TicketFlow.amount)
    await state.update_data(
        ticket_id=ticket_id,
        ticket_trip_id=ticket_trip_id,
    )
    await set_ui_message(callback.message, state, text, keyboard)


@router.callback_query(TicketCB.filter(F.action == "amount_confirm"))
async def cb_ticket_amount_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.message is None or callback.data is None:
        await callback.answer()
        return
    payload = TicketCB.unpack(callback.data)
    try:
        ticket_id = int(payload.value)
    except ValueError:
        await callback.answer("Ticket invalido.", show_alert=True)
        return
    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await callback.answer("El ticket ya no existe.", show_alert=True)
            return
        if ticket.amount is None or ticket.amount_source != "ai_pending":
            await callback.answer(
                "El ticket no tiene un monto pendiente de confirmacion.",
                show_alert=True,
            )
            return
        update_ticket_amount(
            db,
            ticket,
            amount=ticket.amount,
            source="ai",
            ai_model=ticket.ai_model,
            processed_at=ticket.ai_processed_at,
        )
        trip = get_trip(db, ticket.trip_id)
        if trip is None:
            text, keyboard = "El viaje ya no existe.", tickets_menu_kb()
        else:
            text, keyboard = ticket_menu_view(trip)
    await state.clear()
    await callback.answer("Monto confirmado.")
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(TicketCB.filter(F.action == "retry_ai"))
async def cb_ticket_retry_ai(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = TicketCB.unpack(callback.data)
    try:
        ticket_id = int(payload.value)
    except ValueError:
        return
    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await edit_or_send(
                callback.message,
                "El ticket ya no existe.",
                tickets_menu_kb(),
            )
            return
        file_id = ticket.telegram_file_id
        ticket_trip_id = ticket.trip_id
    await state.clear()
    await remember_ui_message(callback, state)
    await state.set_state(TicketFlow.amount)
    await state.update_data(
        ticket_id=ticket_id,
        ticket_trip_id=ticket_trip_id,
    )
    if not ticket_ai.is_enabled():
        text, keyboard = ticket_amount_prompt_view(
            ticket,
            note="El analisis automatico de montos no esta configurado.",
        )
        await set_ui_message(callback.message, state, text, keyboard)
        return

    await set_ui_message(
        callback.message,
        state,
        "<b>Analizando ticket...</b>\n\nEsto puede demorar unos segundos.",
        done_kb(),
    )
    image = await ticket_ai.download_image(callback.bot, file_id, None)
    amount = None
    note = "No se pudo detectar el monto automaticamente."
    if image is not None:
        result = await ticket_ai.extract_ticket_amount(
            image, ticket_ai.detect_image_mime(image)
        )
        if result is not None:
            amount = Decimal(str(result.amount)).quantize(Decimal("0.01"))
    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await state.clear()
            await edit_or_send(
                callback.message,
                "El ticket ya no existe.",
                tickets_menu_kb(),
            )
            return
        if amount is not None:
            update_ticket_amount(
                db,
                ticket,
                amount=amount,
                source="ai_pending",
                ai_model=get_settings().gemini_model,
                processed_at=utcnow_naive(),
            )
            note = "Monto detectado por IA. Confirma que es correcto."
        text, keyboard = ticket_amount_prompt_view(ticket, note=note)
    await set_ui_message(callback.message, state, text, keyboard)


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
    if total == 0:
        await callback.answer(
            "No se pudieron reenviar los tickets.", show_alert=True
        )
        return
    await callback.answer(f"Se reenviaron {total} tickets.")


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
        await callback.answer("Categoría inválida.", show_alert=True)
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
    if total == 0:
        await callback.answer(
            "No se pudieron reenviar los tickets.", show_alert=True
        )
        return
    await callback.answer(f"Se reenviaron {total} tickets.")


@router.message(StateFilter(TicketFlow.amount))
async def receive_ticket_amount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ticket_id = int(data.get("ticket_id") or 0)
    amount = parse_decimal(message.text or "")
    if (
        amount is None
        or amount <= 0
        or amount > ticket_ai.MAX_TICKET_AMOUNT
    ):
        with session_scope() as db:
            ticket = get_ticket(db, ticket_id)
            if ticket is None:
                await state.clear()
                await message.answer("El ticket ya no existe.")
                return
            text, keyboard = ticket_amount_prompt_view(
                ticket,
                note=(
                    "Monto invalido. Escribe un numero mayor a cero "
                    "o usa Quitar monto."
                ),
            )
        await set_ui_message(message, state, text, keyboard)
        return

    with session_scope() as db:
        ticket = get_ticket(db, ticket_id)
        if ticket is None:
            await state.clear()
            await message.answer("El ticket ya no existe.")
            return
        trip_id = ticket.trip_id
        update_ticket_amount(
            db,
            ticket,
            amount=amount.quantize(Decimal("0.01")),
            source="manual",
            ai_model=None,
            processed_at=None,
        )
    view = _amounts_view(trip_id, 0)
    if view is None:
        await state.clear()
        await message.answer("El viaje ya no existe.")
        return
    text, keyboard = view
    await set_ui_message(message, state, text, keyboard)
    await state.clear()


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
        ticket, created = add_ticket(
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
    file_id = photo.file_id
    file_size = photo.file_size
    mime_type = "image/jpeg"
    if not created:
        await message.answer("Esa imagen ya estaba agregada al viaje.")
        return
    await _analyze_ticket(
        message,
        state,
        trip_id=trip_id,
        kind=kind,
        ticket_id=ticket.id,
        file_id=file_id,
        file_size=file_size,
        mime_type=mime_type,
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
        ticket, created = add_ticket(
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
    file_id = document.file_id
    file_size = document.file_size
    mime_type = document.mime_type or "image/jpeg"
    if not created:
        await message.answer("Esa imagen ya estaba agregada al viaje.")
        return
    await _analyze_ticket(
        message,
        state,
        trip_id=trip_id,
        kind=kind,
        ticket_id=ticket.id,
        file_id=file_id,
        file_size=file_size,
        mime_type=mime_type,
    )


@router.message(StateFilter(TicketFlow.media))
async def receive_ticket_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Envía imágenes o pulsa Listo para terminar.")
