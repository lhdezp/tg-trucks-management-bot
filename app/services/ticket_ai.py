from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from io import BytesIO
from typing import Any

from aiogram import Bot
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TICKET_AMOUNT = Decimal("1000000")
PROMPT = (
    "Analiza la imagen de un ticket o recibo de un viaje. "
    "Devuelve el monto total final pagado, incluyendo impuestos y cargos. "
    "No devuelvas el subtotal. Si el ticket muestra propina, incluyela en el total. "
    "No inventes cifras: si no se ve un monto total, usa 0 y explica el motivo. "
    "currency debe ser el codigo o simbolo visible en el ticket, o una cadena vacia. "
    "confidence debe estar entre 0 y 1."
)


class TicketExtraction(BaseModel):
    amount: float = Field(default=0, description="Monto total final del ticket")
    currency: str = Field(default="", description="Moneda visible en el ticket")
    confidence: float = Field(default=0, description="Confianza entre 0 y 1")
    reason: str = Field(default="", description="Motivo si no se pudo leer el monto")


def is_enabled() -> bool:
    return bool(get_settings().gemini_api_key)


async def download_image(
    bot: Bot,
    file_id: str,
    file_size: int | None,
) -> bytes | None:
    if file_size is not None and file_size > MAX_IMAGE_BYTES:
        logger.warning("Ticket demasiado grande para analizar: %s bytes", file_size)
        return None
    buffer = BytesIO()
    try:
        await bot.download(file_id, destination=buffer)
    except Exception:
        logger.exception("No se pudo descargar la imagen del ticket")
        return None
    data = buffer.getvalue()
    if not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        logger.warning("Ticket descargado demasiado grande: %s bytes", len(data))
        return None
    return data


def detect_image_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"


def _parse_response(response: Any) -> TicketExtraction | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, TicketExtraction):
        return parsed
    if isinstance(parsed, dict):
        try:
            return TicketExtraction.model_validate(parsed)
        except Exception:
            return None
    text = getattr(response, "text", None)
    if not text:
        return None
    try:
        return TicketExtraction.model_validate(json.loads(text))
    except Exception:
        return None


async def extract_ticket_amount(
    image_bytes: bytes,
    mime_type: str,
) -> TicketExtraction | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        image_part = types.Part.from_bytes(
            data=image_bytes, mime_type=mime_type
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TicketExtraction,
            temperature=0,
        )
    except Exception:
        logger.exception("No se pudo preparar el cliente de Gemini")
        return None

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=[PROMPT, image_part],
                    config=config,
                ),
                timeout=settings.gemini_timeout_seconds,
            )
            result = _parse_response(response)
            if result is None:
                logger.warning("Gemini no devolvio un monto interpretable")
                return None
            amount = Decimal(str(result.amount))
            if amount <= 0 or amount > MAX_TICKET_AMOUNT:
                logger.info(
                    "Gemini no detecto un monto valido: %s (%s)",
                    result.amount,
                    result.reason,
                )
                return None
            return result
        except Exception as error:
            last_error = error
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
    logger.warning("Fallo el analisis del ticket con Gemini: %s", last_error)
    return None
