from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.callbacks import MenuCB

MENU_BUTTON = "Menú principal"
CANCEL_BUTTON = "Cancelar"


def markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def button(text: str, callback_data) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data.pack())


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MENU_BUTTON),
                KeyboardButton(text=CANCEL_BUTTON),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Usa los botones o escribe un dato",
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [
                button("Viajes", MenuCB(action="trips")),
                button("Camiones", MenuCB(action="trucks")),
            ],
            [
                button("Conductores", MenuCB(action="drivers")),
                button("Tickets", MenuCB(action="tickets")),
            ],
            [
                button("Resumen semanal", MenuCB(action="week_summary")),
                button("Reportes", MenuCB(action="reports")),
            ],
            [
                button("Configuración", MenuCB(action="settings")),
                button("Ayuda", MenuCB(action="help")),
            ],
        ]
    )


def back_to_menu_row() -> list[InlineKeyboardButton]:
    return [button("Menú principal", MenuCB(action="main"))]


def cancel_row() -> list[InlineKeyboardButton]:
    return [button("Cancelar", MenuCB(action="cancel"))]


def trips_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Nuevo viaje", MenuCB(action="trip_new"))],
            [button("Ver viajes", MenuCB(action="trips_list"))],
            back_to_menu_row(),
        ]
    )


def trucks_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Nuevo camión", MenuCB(action="trucks_new"))],
            [button("Ver camiones", MenuCB(action="trucks_list"))],
            back_to_menu_row(),
        ]
    )


def drivers_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Nuevo conductor", MenuCB(action="drivers_new"))],
            [button("Ver conductores", MenuCB(action="drivers_list"))],
            back_to_menu_row(),
        ]
    )


def tickets_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Elegir viaje", MenuCB(action="tickets_list"))],
            back_to_menu_row(),
        ]
    )


def reports_menu_kb() -> InlineKeyboardMarkup:
    return markup(
        [
            [button("Reporte general", MenuCB(action="report_general"))],
            [button("Reporte por camión", MenuCB(action="report_truck"))],
            [button("Resumen semanal", MenuCB(action="week_summary"))],
            back_to_menu_row(),
        ]
    )


def settings_menu_kb() -> InlineKeyboardMarkup:
    return markup([back_to_menu_row()])
