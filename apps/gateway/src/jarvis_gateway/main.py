from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .actions import ActionContext, ActionDefinition, ActionError, build_action_registry
from .audit import AuditLogger
from .models import (
    ActionRequest,
    ActionResponse,
    ConfirmationRequest,
    PendingConfirmation,
    ToolError,
)
from .policy import PolicyError
from .reminders import ReminderStore
from .settings import Settings, get_settings


def _validate_token(
    settings: Settings,
    authorization: str | None,
    x_jarvis_token: str | None,
) -> None:
    if not settings.local_token:
        return

    expected = settings.local_token.get_secret_value()
    provided = ""
    if authorization and authorization.startswith("Bearer "):
        provided = authorization[7:]
    elif x_jarvis_token:
        provided = x_jarvis_token

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token local inválido")


def create_app(
    settings: Settings | None = None,
    action_registry: dict[str, ActionDefinition] | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(title="JARVIS Gateway", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.cors_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Jarvis-Token"],
    )

    registry = action_registry or build_action_registry(app_settings)
    audit = AuditLogger(app_settings.audit_db)
    pending_confirmations: dict[str, PendingConfirmation] = {}
    reminder_store = ReminderStore(app_settings.audit_db)

    async def require_local_token(
        authorization: Annotated[str | None, Header()] = None,
        x_jarvis_token: Annotated[str | None, Header()] = None,
    ) -> None:
        _validate_token(app_settings, authorization, x_jarvis_token)

    async def execute_action(action_def: ActionDefinition, arguments: dict[str, object]) -> ActionResponse:
        start = time.perf_counter()
        action_name = action_def.name
        try:
            parsed_args = action_def.args_model.model_validate(arguments)
            result = await asyncio.wait_for(
                action_def.handler(ActionContext(settings=app_settings), parsed_args),
                timeout=action_def.timeout_seconds,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(action=action_name, risk=action_def.risk, ok=True, duration_ms=duration_ms)
            return ActionResponse(ok=True, action=action_name, result=result)
        except TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(
                action=action_name,
                risk=action_def.risk,
                ok=False,
                duration_ms=duration_ms,
                error_code="timeout",
                error_message="Action timeout",
            )
            return ActionResponse(
                ok=False,
                action=action_name,
                error=ToolError(code="timeout", message="La acción excedió el tiempo límite"),
            )
        except ValidationError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(
                action=action_name,
                risk=action_def.risk,
                ok=False,
                duration_ms=duration_ms,
                error_code="invalid_arguments",
                error_message="Argumentos inválidos",
            )
            return ActionResponse(
                ok=False,
                action=action_name,
                error=ToolError(code="invalid_arguments", message="Argumentos inválidos", details={"errors": exc.errors()}),
            )
        except (ActionError, PolicyError) as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            audit.log(
                action=action_name,
                risk=action_def.risk,
                ok=False,
                duration_ms=duration_ms,
                error_code="policy_error",
                error_message=str(exc),
            )
            return ActionResponse(
                ok=False,
                action=action_name,
                error=ToolError(code="policy_error", message=str(exc)),
            )
    @app.get("/health", dependencies=[Depends(require_local_token)])
    async def health() -> dict[str, object]:
        return {"ok": True, "host": app_settings.host, "actions": len(registry)}

    @app.get("/actions", dependencies=[Depends(require_local_token)])
    async def list_actions() -> dict[str, object]:
        return {
            "actions": [
                {
                    "name": action.name,
                    "description": action.description,
                    "risk": action.risk,
                    "requires_confirmation": action.requires_confirmation,
                    "timeout_seconds": action.timeout_seconds,
                }
                for action in registry.values()
            ]
        }

    @app.get("/reminders/due", dependencies=[Depends(require_local_token)])
    async def due_reminders() -> dict[str, object]:
        return {"reminders": reminder_store.due_without_delivering()}

    @app.get("/reminders/upcoming", dependencies=[Depends(require_local_token)])
    async def upcoming_reminders() -> dict[str, object]:
        return {"reminders": reminder_store.upcoming()}

    @app.post("/reminders/{reminder_id}/delivered", dependencies=[Depends(require_local_token)])
    async def mark_reminder_delivered(reminder_id: str) -> dict[str, object]:
        return {"ok": reminder_store.mark_delivered(reminder_id)}

    @app.post("/action", response_model=ActionResponse, dependencies=[Depends(require_local_token)])
    async def run_action(request: ActionRequest) -> ActionResponse:
        action_def = registry.get(request.action)
        if action_def is None:
            return ActionResponse(
                ok=False,
                action=request.action,
                error=ToolError(code="unknown_action", message="Acción no registrada"),
            )

        try:
            action_def.args_model.model_validate(request.arguments)
        except ValidationError as exc:
            return ActionResponse(
                ok=False,
                action=action_def.name,
                error=ToolError(
                    code="invalid_arguments",
                    message="Argumentos inválidos",
                    details={"errors": exc.errors()},
                ),
            )

        if action_def.requires_confirmation:
            request_id = uuid.uuid4().hex
            token = secrets.token_urlsafe(16)
            pending_confirmations[request_id] = PendingConfirmation(
                request_id=request_id,
                token=token,
                action=action_def.name,
                arguments=request.arguments,
                expires_at=datetime.now(UTC) + timedelta(seconds=app_settings.confirmation_ttl_seconds),
                risk=action_def.risk,
            )
            return ActionResponse(
                ok=False,
                action=action_def.name,
                result={
                    "confirmation_required": True,
                    "request_id": request_id,
                    "confirmation_token": token,
                    "expires_in_seconds": app_settings.confirmation_ttl_seconds,
                },
                error=ToolError(code="confirmation_required", message="Se requiere confirmación explícita"),
            )

        return await execute_action(action_def, request.arguments)

    @app.post("/confirm/{request_id}", response_model=ActionResponse, dependencies=[Depends(require_local_token)])
    async def confirm_action(request_id: str, confirmation: ConfirmationRequest) -> ActionResponse:
        pending = pending_confirmations.get(request_id)
        if not pending:
            return ActionResponse(
                ok=False,
                action="confirm",
                error=ToolError(code="confirmation_not_found", message="Confirmación pendiente no encontrada"),
            )

        if pending.is_expired:
            pending_confirmations.pop(request_id, None)
            return ActionResponse(
                ok=False,
                action=pending.action,
                error=ToolError(code="confirmation_expired", message="La confirmación expiró"),
            )

        if not secrets.compare_digest(confirmation.token, pending.token):
            return ActionResponse(
                ok=False,
                action=pending.action,
                error=ToolError(code="confirmation_invalid", message="Token de confirmación inválido"),
            )

        pending_confirmations.pop(request_id, None)
        action_def = registry[pending.action]
        return await execute_action(action_def, pending.arguments)

    return app


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
