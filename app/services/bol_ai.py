from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.ai_image import parse_structured_response

logger = logging.getLogger(__name__)

PROMPT = (
    "Analiza la imagen de un BOL (Bill of Lading) o documento de carga. "
    "Devuelve estos datos del viaje: "
    "origin (la direccion de origen tan precisa como permiten los datos "
    "visibles en la imagen: calle y numero si aparecen, si no ciudad y estado, "
    "o lo que se pueda leer; transcribir y literalizar lo que se ve, sin "
    "inventar precision que no este en la imagen), "
    "destination (la direccion de destino tan precisa como permiten los datos "
    "visibles en la imagen: calle y numero si aparecen, si no ciudad y estado, "
    "o lo que se pueda leer; transcribir y literalizar lo que se ve, sin "
    "inventar precision que no este en la imagen), "
    "bol_number (numero de BOL, numero de carga o de manifiesto tal como aparece), "
    "date (fecha del viaje en formato ISO AAAA-MM-DD), "
    "weight_lb (peso de la carga en libras; si el documento muestra kilogramos, "
    "convierte a libras multiplicando por 2.20462 y explica la conversion en reason), "
    "distance_miles (distancia en millas; si el documento muestra kilometros, "
    "convierte a millas multiplicando por 0.621371 y explica la conversion en reason). "
    "No inventes datos: si un campo no aparece en el documento, usa cadena vacia "
    "para los textos o 0 para los numeros. "
    "confidence debe estar entre 0 y 1. "
    "reason debe explicar que no se encontro o que se convirtio, si corresponde."
)


class BolExtraction(BaseModel):
    origin: str = Field(
        default="",
        description="Origen del viaje, tan preciso como permiten los datos visibles en la imagen",
    )
    destination: str = Field(
        default="",
        description="Destino del viaje, tan preciso como permiten los datos visibles en la imagen",
    )
    bol_number: str = Field(default="", description="Numero de BOL o de carga")
    date: str = Field(default="", description="Fecha en formato ISO AAAA-MM-DD")
    weight_lb: float = Field(default=0, description="Peso de la carga en libras")
    distance_miles: float = Field(default=0, description="Distancia en millas")
    confidence: float = Field(default=0, description="Confianza entre 0 y 1")
    reason: str = Field(default="", description="Motivo si faltan datos")


def is_enabled() -> bool:
    return bool(get_settings().gemini_api_key)


def _parse_response(response) -> BolExtraction | None:
    result = parse_structured_response(response, BolExtraction)
    return result  # type: ignore[return-value]


async def extract_bol_data(
    image_bytes: bytes,
    mime_type: str,
) -> BolExtraction | None:
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
            response_schema=BolExtraction,
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
                logger.warning("Gemini no devolvio un BOL interpretable")
                return None
            return result
        except Exception as error:
            last_error = error
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
    logger.warning("Fallo el analisis del BOL con Gemini: %s", last_error)
    return None
