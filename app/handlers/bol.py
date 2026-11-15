from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.callbacks import BolCB, MenuCB
from app.config import get_settings
from app.handlers.trips import (
    _delete_user_message,
    _field_prompt,
    _show_truck_selection,
    _trucks_drivers_ready,
    validate_trip_field,
)
from app.keyboards import button, markup
from app.services import bol_ai
from app.services.ai_image import download_image
from app.states import TripBOL
from app.ui import set_ui_message
from app.utils import FIELD_LABELS, format_date, format_number, safe_escape

router = Router(name="bol")

BOL_FIELDS = ["origin", "destination", "bol_number", "date", "weight", "distance"]
KEY_MAP = {
    "origin": "origin",
    "destination": "destination",
    "bol_number": "bol_number",
    "date": "trip_date",
    "weight": "weight",
    "distance": "distance",
}


def _bol_prompt(field: str) -> str:
    if field == "bol_number":
        return "Escribe el número de BOL."
    return _field_prompt(field)


def _missing_fields(data: dict) -> list[str]:
    return [
        field
        for field in BOL_FIELDS
        if not data.get(KEY_MAP[field])
    ]


def _media_kb():
    return markup([[button("Cancelar", MenuCB(action="cancel"))]])


def _input_kb(correction: bool):
    if correction:
        return markup(
            [
                [
                    button("Atrás", BolCB(action="back_to_confirm")),
                    button("Cancelar", MenuCB(action="cancel")),
                ]
            ]
        )
    return markup([[button("Cancelar", MenuCB(action="cancel"))]])


def _fail_kb():
    return markup(
        [
            [button("Reintentar", BolCB(action="retry"))],
            [button("Cargar viaje manualmente", MenuCB(action="trip_new"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def _disabled_kb():
    return markup(
        [
            [button("Cargar viaje manualmente", MenuCB(action="trip_new"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def _confirm_kb():
    return markup(
        [
            [button("Sí, son correctos", BolCB(action="confirm"))],
            [button("Corregir un dato", BolCB(action="correct"))],
            [button("Cancelar", MenuCB(action="cancel"))],
        ]
    )


def _correct_kb():
    rows: list[list] = []
    current: list = []
    for field in BOL_FIELDS:
        current.append(
            button(FIELD_LABELS[field], BolCB(action="field_edit", value=field))
        )
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([button("Atrás", BolCB(action="back_to_confirm"))])
    rows.append([button("Cancelar", MenuCB(action="cancel"))])
    return markup(rows)


def _confirm_text(data: dict) -> str:
    settings = get_settings()
    trip_date = date.fromisoformat(data["trip_date"])
    return (
        "<b>Confirma los datos del BOL</b>\n\n"
        f"Origen: {safe_escape(data['origin'])}\n"
        f"Destino: {safe_escape(data['destination'])}\n"
        f"BOL: <code>{safe_escape(data['bol_number'])}</code>\n"
        f"Fecha: {format_date(trip_date)}\n"
        f"Peso: {format_number(data['weight'])} {settings.weight_unit}\n"
        f"Millas: {format_number(data['distance'])}"
    )


async def _ask_bol_field(
    message: Message,
    state: FSMContext,
    field: str,
    error: str | None = None,
) -> None:
    data = await state.get_data()
    correction = bool(data.get("bol_correcting"))
    await state.set_state(TripBOL.input)
    await state.update_data(bol_field=field)
    text = _bol_prompt(field)
    if error:
        text = f"<b>{error}</b>\n\n{text}"
    await set_ui_message(message, state, text, _input_kb(correction))


async def _show_bol_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(TripBOL.confirm)
    await state.update_data(bol_correcting=False)
    await set_ui_message(message, state, _confirm_text(data), _confirm_kb())


async def _begin_bol(
    message: Message, state: FSMContext, ui_msg_id: int | None = None
) -> None:
    await state.clear()
    if ui_msg_id:
        await state.update_data(ui_msg_id=ui_msg_id)
    await state.set_state(TripBOL.media)
    await set_ui_message(
        message,
        state,
        "<b>Nuevo viaje con BOL</b>\n\nEnvía la imagen del BOL (foto o documento).",
        _media_kb(),
    )


def _validated_from_extraction(result: bol_ai.BolExtraction) -> dict:
    values: dict = {}

    text_value, error = validate_trip_field("origin", result.origin or "")
    if error is None:
        values["origin"] = text_value
    text_value, error = validate_trip_field("destination", result.destination or "")
    if error is None:
        values["destination"] = text_value

    bol_value, error = validate_trip_field("bol_number", result.bol_number or "")
    if error is None:
        values["bol_number"] = bol_value

    if result.date:
        date_value, error = validate_trip_field("date", result.date)
        if error is None:
            values["trip_date"] = date_value.isoformat()

    if result.weight_lb and result.weight_lb > 0:
        weight_value, error = validate_trip_field(
            "weight", str(result.weight_lb)
        )
        if error is None:
            values["weight"] = weight_value

    if result.distance_miles and result.distance_miles > 0:
        distance_value, error = validate_trip_field(
            "distance", str(result.distance_miles)
        )
        if error is None:
            values["distance"] = distance_value

    return values


async def _analyze_bol(
    message: Message,
    state: FSMContext,
    *,
    file_id: str,
    file_size: int | None,
    mime_type: str,
) -> None:
    if not bol_ai.is_enabled():
        await set_ui_message(
            message,
            state,
            "<b>Nuevo viaje con BOL</b>\n\n"
            "El análisis automático no está configurado. "
            "Puedes registrar el viaje manualmente.",
            _disabled_kb(),
        )
        return

    await set_ui_message(
        message,
        state,
        "<b>Analizando BOL...</b>\n\nEsto puede demorar unos segundos.",
        _media_kb(),
    )
    image = await download_image(message.bot, file_id, file_size)
    if image is None:
        await set_ui_message(
            message,
            state,
            "No pude descargar la imagen. Intenta con otra imagen "
            "o carga el viaje manualmente.",
            _fail_kb(),
        )
        return

    result = await bol_ai.extract_bol_data(image, mime_type)
    if result is None:
        await set_ui_message(
            message,
            state,
            "No pude leer el BOL. Asegurate de que la imagen sea clara "
            "y reintenta, o carga el viaje manualmente.",
            _fail_kb(),
        )
        return

    values = _validated_from_extraction(result)
    if values:
        await state.update_data(**values)
    prefilled = [
        KEY_MAP[field]
        for field in BOL_FIELDS
        if values.get(KEY_MAP[field]) is not None
    ]
    await state.update_data(prefilled=prefilled, bol_correcting=False)
    data = await state.get_data()
    missing = _missing_fields(data)
    if missing:
        await _ask_bol_field(message, state, missing[0])
        return
    await _show_bol_confirm(message, state)


@router.message(Command("nuevobol"))
async def cmd_new_bol(message: Message, state: FSMContext) -> None:
    await _begin_bol(message, state)


@router.callback_query(MenuCB.filter(F.action == "trip_new_bol"))
async def cb_trip_new_bol(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _begin_bol(callback.message, state, callback.message.message_id)


@router.message(StateFilter(TripBOL.media), F.photo)
async def receive_bol_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    await _analyze_bol(
        message,
        state,
        file_id=photo.file_id,
        file_size=photo.file_size,
        mime_type="image/jpeg",
    )


@router.message(StateFilter(TripBOL.media), F.document)
async def receive_bol_document(message: Message, state: FSMContext) -> None:
    document = message.document
    if document is None or not (document.mime_type or "").startswith("image/"):
        await message.answer("Solo se aceptan imágenes del BOL.")
        return
    await _analyze_bol(
        message,
        state,
        file_id=document.file_id,
        file_size=document.file_size,
        mime_type=document.mime_type or "image/jpeg",
    )


@router.message(StateFilter(TripBOL.media))
async def receive_bol_media_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Envía una imagen del BOL o pulsa Cancelar.")


@router.message(StateFilter(TripBOL.input), F.text)
async def receive_bol_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("bol_field")
    if not field:
        return
    value, error = validate_trip_field(field, message.text or "")
    await _delete_user_message(message)
    if error:
        await _ask_bol_field(message, state, field, error)
        return
    key = "trip_date" if field == "date" else field
    if field == "date":
        await state.update_data({key: value.isoformat()})
    else:
        await state.update_data({key: value})
    data = await state.get_data()
    prefilled = list(data.get("prefilled", []))
    if key not in prefilled:
        prefilled.append(key)
        await state.update_data(prefilled=prefilled)
    if data.get("bol_correcting"):
        await _show_bol_confirm(message, state)
        return
    data = await state.get_data()
    missing = _missing_fields(data)
    if missing:
        await _ask_bol_field(message, state, missing[0])
        return
    await _show_bol_confirm(message, state)


@router.message(StateFilter(TripBOL.input))
async def receive_bol_input_invalid(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("bol_field", "origin")
    await _delete_user_message(message)
    await _ask_bol_field(message, state, field, "Envía el dato como texto.")


@router.message(StateFilter(TripBOL.confirm))
async def receive_bol_confirm_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("Usa los botones para confirmar los datos del BOL.")


@router.callback_query(BolCB.filter(F.action == "retry"))
async def cb_bol_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    cleared = {KEY_MAP[field]: None for field in BOL_FIELDS}
    await state.update_data(
        **cleared, prefilled=[], bol_correcting=False, bol_field=None
    )
    await state.set_state(TripBOL.media)
    await set_ui_message(
        callback.message,
        state,
        "<b>Nuevo viaje con BOL</b>\n\nEnvía otra imagen del BOL (foto o documento).",
        _media_kb(),
    )


@router.callback_query(BolCB.filter(F.action == "correct"))
async def cb_bol_correct(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await set_ui_message(
        callback.message,
        state,
        "<b>Corregir dato</b>\n\nElige el dato que quieres corregir.",
        _correct_kb(),
    )


@router.callback_query(BolCB.filter(F.action == "field_edit"))
async def cb_bol_field_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    payload = BolCB.unpack(callback.data)
    if payload.value not in BOL_FIELDS:
        return
    await state.update_data(bol_correcting=True)
    await _ask_bol_field(callback.message, state, payload.value)


@router.callback_query(BolCB.filter(F.action == "back_to_confirm"))
async def cb_bol_back_to_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _show_bol_confirm(callback.message, state)


@router.callback_query(BolCB.filter(F.action == "confirm"))
async def cb_bol_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    missing = _missing_fields(data)
    if missing:
        await _ask_bol_field(callback.message, state, missing[0])
        return
    prefilled = [
        KEY_MAP[field]
        for field in BOL_FIELDS
        if data.get(KEY_MAP[field]) is not None
    ]
    await state.update_data(prefilled=prefilled, bol_correcting=False)
    if await _trucks_drivers_ready(callback.message, state):
        await _show_truck_selection(callback.message, state, 0)
