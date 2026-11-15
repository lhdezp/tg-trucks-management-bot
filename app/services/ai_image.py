from __future__ import annotations

import json
import logging
from io import BytesIO
from typing import Any

from aiogram import Bot
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def download_image(
    bot: Bot,
    file_id: str,
    file_size: int | None,
) -> bytes | None:
    if file_size is not None and file_size > MAX_IMAGE_BYTES:
        logger.warning("Imagen demasiado grande para analizar: %s bytes", file_size)
        return None
    buffer = BytesIO()
    try:
        await bot.download(file_id, destination=buffer)
    except Exception:
        logger.exception("No se pudo descargar la imagen")
        return None
    data = buffer.getvalue()
    if not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        logger.warning("Imagen descargada demasiado grande: %s bytes", len(data))
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


def parse_structured_response(
    response: Any, model: type[BaseModel]
) -> BaseModel | None:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, model):
        return parsed
    if isinstance(parsed, dict):
        try:
            return model.model_validate(parsed)
        except Exception:
            return None
    text = getattr(response, "text", None)
    if not text:
        return None
    try:
        return model.model_validate(json.loads(text))
    except Exception:
        return None
