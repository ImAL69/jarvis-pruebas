from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        enable_decoding=False,
    )

    host: Literal["127.0.0.1"] = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8765, alias="PORT")
    allowed_dirs: list[Path] = Field(default_factory=list, alias="JARVIS_ALLOWED_DIRS")
    audit_db: Path = Field(default=Path("./data/jarvis.sqlite3"), alias="JARVIS_AUDIT_DB")
    require_confirmation: bool = Field(default=True, alias="JARVIS_REQUIRE_CONFIRMATION")
    allow_shell: bool = Field(default=False, alias="JARVIS_ALLOW_SHELL")
    log_transcripts: bool = Field(default=False, alias="JARVIS_LOG_TRANSCRIPTS")
    local_token: SecretStr | None = Field(default=None, alias="JARVIS_LOCAL_TOKEN")
    timezone: str = "UTC"
    cors_origin: str = Field(default="http://127.0.0.1:5173", alias="JARVIS_CORS_ORIGIN")
    confirmation_ttl_seconds: int = Field(default=120, ge=15, le=600)
    max_note_filename_len: int = Field(default=80, ge=8, le=120)
    max_note_content_bytes: int = Field(default=4096, ge=32, le=20000)

    @field_validator("allowed_dirs", mode="before")
    @classmethod
    def _parse_dirs(cls, value: object) -> list[Path]:
        if value is None:
            return []
        if isinstance(value, str):
            return [Path(item.strip()) for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [Path(str(item)).expanduser() for item in value]
        raise ValueError("JARVIS_ALLOWED_DIRS debe ser una lista o string separado por comas")

    @model_validator(mode="after")
    def _validate_dirs(self) -> Settings:
        if not self.allowed_dirs:
            raise ValueError("Debe configurar JARVIS_ALLOWED_DIRS con al menos un directorio permitido")
        resolved: list[Path] = []
        for directory in self.allowed_dirs:
            real_dir = directory.expanduser().resolve()
            if not real_dir.exists() or not real_dir.is_dir():
                raise ValueError(f"Directorio permitido no existe o no es carpeta: {directory}")
            resolved.append(real_dir)
        self.allowed_dirs = resolved
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
