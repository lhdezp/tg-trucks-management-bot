from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str
    admin_ids: str
    db_path: Path = Path("data/bot.db")
    timezone: str = "UTC"
    currency: str = "$"
    weight_unit: str = "lb"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_timeout_seconds: float = 20.0

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def validate_gemini_api_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("admin_ids")
    @classmethod
    def validate_admin_ids(cls, value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise ValueError("ADMIN_IDS debe contener al menos un ID de Telegram.")
        try:
            ids = [int(part) for part in parts]
        except ValueError as exc:
            raise ValueError(
                "ADMIN_IDS debe ser una lista de IDs numéricos separados por comas."
            ) from exc
        if any(item <= 0 for item in ids):
            raise ValueError("ADMIN_IDS contiene un ID inválido.")
        return ",".join(str(item) for item in ids)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"TIMEZONE inválida: {value}") from exc
        return value

    @property
    def admin_id_set(self) -> frozenset[int]:
        return frozenset(int(item) for item in self.admin_ids.split(","))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
