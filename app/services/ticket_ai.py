from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.ai_image import (
    MAX_IMAGE_BYTES,
    detect_image_mime,
    download_image,
    parse_structured_response,
)

logger = logging.getLogger(__name__)

MAX_TICKET_AMOUNT = Decimal("1000000")
PROMPT = (
    "Analiza la imagen de un ticket o recibo de un viaje. "
    "Devuelve el monto total final pagado, incluyendo impuestos y cargos. "
    "No devuelvas el subtotal. Si el ticket muestra propina, incluyela en el total. "
    "No inventes cifras: si no se ve un monto total, usa 0 y explica el motivo. "
    "currency debe ser el codigo o simbolo visible en el ticket, o una cadena vacia. "
    "confidence debe estar entre 0 y 1."
)

__all__ = [
    "MAX_IMAGE_BYTES",
    "MAX_TICKET_AMOUNT",
    "PROMPT",
    "TicketExtraction",
    "detect_image_mime",
    "download_image",
    "extract_ticket_amount",
    "is_enabled",
]


class TicketExtraction(BaseModel):
    amount: float = Field(default=0, description="Monto total final del ticket")
    currency: str = Field(default="", description="Moneda visible en el ticket")
    confidence: float = Field(default=0, description="Confianza entre 0 y 1")
    reason: str = Field(default="", description="Motivo si no se pudo leer el monto")


def is_enabled() -> bool:
    return bool(get_settings().gemini_api_key)


def _parse_response(response: Any) -> TicketExtraction | None:
    result = parse_structured_response(response, TicketExtraction)
    return result  # type: ignore[return-value]


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
