from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import MenuCB
from app.keyboards import CANCEL_BUTTON, MENU_BUTTON, main_menu_kb, main_reply_kb
from app.ui import edit_or_send
from app.views import main_menu_view

router = Router(name="common")

WELCOME = (
    "<b>Gestión de camiones</b>\n\n"
    "Desde aquí puedes registrar viajes, camiones y conductores, adjuntar "
    "tickets y generar reportes semanales.\n\n"
    "Usa el botón <b>Menú principal</b> para volver a la navegación."
)

HELP_TEXT = (
    "<b>Ayuda</b>\n\n"
    "<b>Navegación</b>\n"
    "Todo se puede hacer con los botones del menú. El teclado inferior tiene "
    "Menú principal y Cancelar para salir de cualquier paso.\n\n"
    "<b>Comandos disponibles</b>\n"
    "/start — Inicio\n"
    "/menu — Menú principal\n"
    "/viajes — Lista de viajes\n"
    "/nuevoviaje — Registrar un viaje\n"
    "/camiones — Administrar camiones\n"
    "/conductores — Administrar conductores\n"
    "/tickets — Administrar tickets de un viaje\n"
    "/semana — Resumen de texto de la semana actual\n"
    "/reporte — Excel general de la semana actual\n"
    "/reporte DD/MM/AAAA — Excel de la semana de esa fecha\n"
    "/configuracion — Reporte automático\n"
    "/cancelar — Cancelar el paso actual\n\n"
    "<b>Semana</b>\n"
    "Los reportes siempre van de lunes a domingo."
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_reply_kb())
    text, keyboard = main_menu_view()
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = main_menu_view()
    await message.answer(text, reply_markup=keyboard)


@router.message(F.text == MENU_BUTTON)
async def menu_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = main_menu_view()
    await message.answer(text, reply_markup=keyboard)


async def cancel_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, keyboard = main_menu_view()
    await message.answer("Operación cancelada.\n\n" + text, reply_markup=keyboard)


@router.message(Command("cancelar"))
@router.message(F.text == CANCEL_BUTTON)
async def cancel_button(message: Message, state: FSMContext) -> None:
    await cancel_flow(message, state)


@router.callback_query(MenuCB.filter(F.action == "main"))
async def callback_main(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    text, keyboard = main_menu_view()
    await edit_or_send(callback.message, text, keyboard)


@router.callback_query(MenuCB.filter(F.action == "cancel"))
async def callback_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is None:
        return
    text, keyboard = main_menu_view()
    await edit_or_send(callback.message, "Operación cancelada.\n\n" + text, keyboard)


@router.callback_query(MenuCB.filter(F.action == "help"))
async def callback_help(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await edit_or_send(callback.message, HELP_TEXT, main_menu_kb())


@router.message(Command("ayuda"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb())
