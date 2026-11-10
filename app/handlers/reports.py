from __future__ import annotations

from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import MenuCB, ReportCB
from app.database import session_scope
from app.keyboards import (
    button,
    cancel_row,
    markup,
    reports_menu_kb,
)
from app.services.queries import (
    get_truck,
    list_trucks,
    trips_for_report,
)
from app.services.reports import send_summary, send_week_report
from app.services.weeks import (
    current_week_bounds,
    previous_week_bounds,
    today_local,
    week_bounds,
)
from app.states import ReportFlow
from app.ui import edit_or_send, set_ui_message
from app.utils import format_date, format_week_range, parse_date_text
from app.views import (
    report_menu_view,
    report_truck_list_view,
    report_week_view,
)

router = Router(name="reports")


def _scope_week_bounds(scope: str) -> tuple[date, date]:
    if scope == "previous":
        return previous_week_bounds()
    return current_week_bounds()


async def _show_week_view(
    message: Message, scope: str, truck_id: int
) -> None:
    truck_name: str | None = None
    if scope == "truck" and truck_id:
        with session_scope() as db:
            truck = get_truck(db, truck_id)
            if truck is None:
                await edit_or_send(
                    message,
                    "El camión seleccionado ya no existe.",
                    reports_menu_kb(),
                )
                return
            truck_name = truck.name
            truck_id = truck.id
    text, keyboard = report_week_view(scope, truck_id, truck_name)
    await edit_or_send(message, text, keyboard)


async def _show_truck_list(message: Message, page: int) -> None:
    with session_scope() as db:
        trucks, has_next = list_trucks(db, page)
        text, keyboard = report_truck_list_view(trucks, page, has_next)
    await edit_or_send(message, text, keyboard)


def _custom_date_kb() -> object:
    return markup([cancel_row()])


async def _ask_custom_date(
    message: Message, state: FSMContext, scope: str, truck_id: int
) -> None:
    await state.set_state(ReportFlow.date)
    await state.update_data(report_scope=scope, report_truck_id=truck_id)
    await set_ui_message(
        message,
        state,
        (
            "<b>Otra fecha</b>\n\n"
            "Escribe una fecha dentro de la semana que quieres reportar "
            "(por ejemplo <code>05/11/2026</code>)."
        ),
        _custom_date_kb(),
    )


async def _send_and_confirm(
    bot: Bot,
    chat_id: int,
    scope: str,
    truck_id: int,
    week_start: date,
    week_end: date,
) -> bool:
    return await send_week_report(
        bot,
        chat_id,
        week_start,
        week_end,
        scope=scope,
        truck_id=truck_id,
    )


@router.message(Command("semana"))
async def cmd_week_summary(message: Message, state: FSMContext) -> None:
    await state.clear()
    start, end = current_week_bounds()
    with session_scope() as db:
        trips = trips_for_report(db, start, end)
    await send_summary(message.bot, message.chat.id, trips, start, end)


@router.message(Command("reporte"))
async def cmd_report(
    message: Message, command: CommandObject, state: FSMContext
) -> None:
    await state.clear()
    args = (command.args or "").strip()
    if args:
        anchor = parse_date_text(args)
        if anchor is None:
            await message.answer(
                "No entendí la fecha. Usa el formato <code>DD/MM/AAAA</code>."
            )
            return
        start, end = week_bounds(anchor)
    else:
        start, end = current_week_bounds()
    await _send_and_confirm(
        message.bot,
        message.chat.id,
        "general",
        0,
        start,
        end,
    )


@router.callback_query(MenuCB.filter(F.action == "reports"))
async def cb_reports_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    text, keyboard = report_menu_view()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(MenuCB.filter(F.action == "report_general"))
async def cb_report_general(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_week_view(callback.message, "general", 0)


@router.callback_query(MenuCB.filter(F.action == "report_truck"))
async def cb_report_truck(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await _show_truck_list(callback.message, 0)


@router.callback_query(MenuCB.filter(F.action == "week_summary"))
async def cb_week_summary(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    start, end = current_week_bounds()
    with session_scope() as db:
        trips = trips_for_report(db, start, end)
    await send_summary(callback.bot, callback.message.chat.id, trips, start, end)


@router.callback_query(ReportCB.filter(F.action == "scope_menu"))
async def cb_report_scope_menu(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    text, keyboard = report_menu_view()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(ReportCB.filter(F.action == "truck_scope"))
async def cb_report_truck_scope(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = ReportCB.unpack(callback.data)
    await _show_truck_list(callback.message, payload.page)


@router.callback_query(ReportCB.filter(F.action == "truck"))
async def cb_report_truck_pick(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = ReportCB.unpack(callback.data)
    await _show_week_view(callback.message, "truck", payload.truck_id)


@router.callback_query(ReportCB.filter(F.action == "week"))
async def cb_report_week(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Generando reporte...")
    await state.clear()
    if callback.message is None or callback.data is None:
        return
    payload = ReportCB.unpack(callback.data)
    scope = payload.scope or "general"
    start, end = _scope_week_bounds(payload.week)
    await _send_and_confirm(
        callback.bot,
        callback.message.chat.id,
        scope,
        payload.truck_id,
        start,
        end,
    )


@router.callback_query(ReportCB.filter(F.action == "custom"))
async def cb_report_custom(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = ReportCB.unpack(callback.data)
    scope = payload.scope or "general"
    await _ask_custom_date(callback.message, state, scope, payload.truck_id)


@router.message(StateFilter(ReportFlow.date))
async def receive_report_date(message: Message, state: FSMContext) -> None:
    anchor = parse_date_text(message.text or "")
    if anchor is None:
        data = await state.get_data()
        await _ask_custom_date(
            message,
            state,
            str(data.get("report_scope") or "general"),
            int(data.get("report_truck_id") or 0),
        )
        await message.answer(
            "No entendí la fecha. Usa el formato <code>DD/MM/AAAA</code>."
        )
        return
    data = await state.get_data()
    scope = str(data.get("report_scope") or "general")
    truck_id = int(data.get("report_truck_id") or 0)
    start, end = week_bounds(anchor)
    await _send_and_confirm(
        message.bot,
        message.chat.id,
        scope,
        truck_id,
        start,
        end,
    )
    await set_ui_message(
        message,
        state,
        (
            f"Reporte solicitado para la semana del "
            f"{format_week_range(start, end)}.\n"
            f"Fecha de referencia: {format_date(today_local())}."
        ),
        reports_menu_kb(),
    )
    await state.clear()
