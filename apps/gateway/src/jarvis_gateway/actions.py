from __future__ import annotations

import uuid
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

from .policy import resolve_allowed_path
from .reminders import ReminderStore
from .settings import Settings

RiskLevel = Literal["low", "medium", "high"]


class ActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionContext:
    settings: Settings


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListAllowedFilesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(default=".", min_length=1, max_length=200)


SafeFilename = StringConstraints(pattern=r"^[a-zA-Z0-9._-]{1,80}$", min_length=1, max_length=80)


class CreateNoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(default=".", min_length=1, max_length=200)
    filename: Annotated[str, SafeFilename]
    content: str = Field(min_length=1, max_length=4096)


class OpenUrlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class CreateReminderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    remind_at: datetime


class ListRemindersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


HandlerType = Callable[[ActionContext, BaseModel], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    risk: RiskLevel
    requires_confirmation: bool
    timeout_seconds: float
    handler: HandlerType


async def _get_time_handler(ctx: ActionContext, _: BaseModel) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"iso": now.isoformat(), "timezone": ctx.settings.timezone}


async def _list_allowed_files_handler(ctx: ActionContext, args: BaseModel) -> dict[str, Any]:
    parsed = ListAllowedFilesArgs.model_validate(args.model_dump())
    directory, root = resolve_allowed_path(ctx.settings.allowed_dirs, parsed.directory)
    if not directory.exists() or not directory.is_dir():
        raise ActionError("La carpeta solicitada no existe o no es un directorio")

    files: list[str] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name.startswith("."):
            continue
        if entry.is_symlink():
            target = entry.resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
        files.append(entry.name)

    return {"directory": str(directory), "files": files}


async def _create_note_handler(ctx: ActionContext, args: BaseModel) -> dict[str, Any]:
    parsed = CreateNoteArgs.model_validate(args.model_dump())
    target_dir, _ = resolve_allowed_path(ctx.settings.allowed_dirs, parsed.directory)
    if not target_dir.exists() or not target_dir.is_dir():
        raise ActionError("La carpeta de destino no existe")

    file_path = (target_dir / parsed.filename).resolve()
    if file_path.exists():
        raise ActionError("La nota ya existe")
    content_bytes = parsed.content.encode("utf-8")
    if len(content_bytes) > ctx.settings.max_note_content_bytes:
        raise ActionError("El contenido supera el tamaño máximo permitido")

    file_path.write_text(parsed.content, encoding="utf-8")
    return {"created": True, "path": str(file_path)}


async def _open_url_handler(_: ActionContext, args: BaseModel) -> dict[str, Any]:
    parsed = OpenUrlArgs.model_validate(args.model_dump())
    scheme = parsed.url.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ActionError("Solo se permiten URLs HTTP/HTTPS")
    opened = webbrowser.open(str(parsed.url), new=2)
    return {"url": str(parsed.url), "opened": bool(opened)}


async def _create_reminder_handler(ctx: ActionContext, args: BaseModel) -> dict[str, Any]:
    parsed = CreateReminderArgs.model_validate(args.model_dump())
    remind_at = parsed.remind_at
    if remind_at.tzinfo is None:
        # Voice clients often send local wall-clock time without an offset.
        # Interpret it in the gateway's local timezone, then store UTC.
        local_timezone = datetime.now().astimezone().tzinfo
        remind_at = remind_at.replace(tzinfo=local_timezone).astimezone(UTC)
    if remind_at <= datetime.now(UTC):
        raise ActionError("La fecha del recordatorio debe estar en el futuro")
    return ReminderStore(ctx.settings.audit_db).create(uuid.uuid4().hex, parsed.title, remind_at)


async def _list_reminders_handler(ctx: ActionContext, _: BaseModel) -> dict[str, Any]:
    return {"reminders": ReminderStore(ctx.settings.audit_db).upcoming()}


def build_action_registry(settings: Settings) -> dict[str, ActionDefinition]:
    return {
        "get_time": ActionDefinition(
            name="get_time",
            description="Devuelve la hora UTC actual y zona horaria configurada",
            args_model=EmptyArgs,
            risk="low",
            requires_confirmation=False,
            timeout_seconds=2,
            handler=_get_time_handler,
        ),
        "list_allowed_files": ActionDefinition(
            name="list_allowed_files",
            description="Lista archivos visibles en un directorio permitido",
            args_model=ListAllowedFilesArgs,
            risk="low",
            requires_confirmation=False,
            timeout_seconds=3,
            handler=_list_allowed_files_handler,
        ),
        "create_note": ActionDefinition(
            name="create_note",
            description="Crea una nota de texto en un directorio permitido",
            args_model=CreateNoteArgs,
            risk="medium",
            requires_confirmation=settings.require_confirmation,
            timeout_seconds=4,
            handler=_create_note_handler,
        ),
        "open_url": ActionDefinition(
            name="open_url",
            description="Abre una URL HTTP/HTTPS en el navegador local",
            args_model=OpenUrlArgs,
            risk="medium",
            requires_confirmation=settings.require_confirmation,
            timeout_seconds=4,
            handler=_open_url_handler,
        ),
        "create_reminder": ActionDefinition(
            name="create_reminder",
            description="Programa un recordatorio persistente y seguro",
            args_model=CreateReminderArgs,
            risk="medium",
            requires_confirmation=False,
            timeout_seconds=4,
            handler=_create_reminder_handler,
        ),
        "list_reminders": ActionDefinition(
            name="list_reminders",
            description="Lista recordatorios pendientes",
            args_model=ListRemindersArgs,
            risk="low",
            requires_confirmation=False,
            timeout_seconds=3,
            handler=_list_reminders_handler,
        ),
    }
