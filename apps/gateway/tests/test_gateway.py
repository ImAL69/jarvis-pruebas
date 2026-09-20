from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from jarvis_gateway.actions import ActionContext, build_action_registry
from jarvis_gateway.main import create_app
from jarvis_gateway.settings import Settings


def build_settings(tmp_path: Path, token: str | None = None) -> Settings:
    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        JARVIS_ALLOWED_DIRS=[allowed],
        JARVIS_AUDIT_DB=data_dir / "jarvis.sqlite3",
        JARVIS_REQUIRE_CONFIRMATION=True,
        JARVIS_ALLOW_SHELL=False,
        JARVIS_LOCAL_TOKEN=token,
    )


def test_health_endpoint(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_unknown_action_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.post("/action", json={"action": "unknown", "arguments": {}})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "unknown_action"


def test_path_traversal_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.post(
        "/action",
        json={"action": "list_allowed_files", "arguments": {"directory": "../"}},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_symlink_outside_root_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    allowed = settings.allowed_dirs[0]
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "unsafe").symlink_to(outside, target_is_directory=True)

    client = TestClient(create_app(settings))
    response = client.post(
        "/action",
        json={"action": "list_allowed_files", "arguments": {"directory": "unsafe"}},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_create_note_without_confirmation_rejected(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.post(
        "/action",
        json={
            "action": "create_note",
            "arguments": {"directory": ".", "filename": "note.txt", "content": "hola"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "confirmation_required"


def test_create_note_confirmed_executes_inside_root(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    initial = client.post(
        "/action",
        json={
            "action": "create_note",
            "arguments": {"directory": ".", "filename": "note.txt", "content": "hola"},
        },
    )
    payload = initial.json()

    confirm = client.post(
        f"/confirm/{payload['result']['request_id']}",
        json={"token": payload["result"]["confirmation_token"]},
    )

    assert confirm.status_code == 200
    assert confirm.json()["ok"] is True
    created_file = settings.allowed_dirs[0] / "note.txt"
    assert created_file.exists()


def test_open_url_rejects_non_http_protocols(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.post(
        "/action",
        json={"action": "open_url", "arguments": {"url": "ftp://example.com"}},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_handler_errors_never_return_ok_true(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    first = client.post(
        "/action",
        json={
            "action": "create_note",
            "arguments": {"directory": ".", "filename": "dup.txt", "content": "uno"},
        },
    ).json()
    client.post(f"/confirm/{first['result']['request_id']}", json={"token": first["result"]["confirmation_token"]})

    second = client.post(
        "/action",
        json={
            "action": "create_note",
            "arguments": {"directory": ".", "filename": "dup.txt", "content": "dos"},
        },
    ).json()
    confirm = client.post(
        f"/confirm/{second['result']['request_id']}",
        json={"token": second["result"]["confirmation_token"]},
    )

    assert confirm.status_code == 200
    assert confirm.json()["ok"] is False


def test_timeout_registered_correctly(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    class SleepArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    async def sleeper(_: ActionContext, __: BaseModel) -> dict[str, str]:
        await asyncio.sleep(0.2)
        return {"done": "yes"}

    registry = build_action_registry(settings)
    registry["get_time"] = replace(
        registry["get_time"],
        args_model=SleepArgs,
        timeout_seconds=0.01,
        handler=sleeper,
    )

    client = TestClient(create_app(settings, action_registry=registry))
    response = client.post("/action", json={"action": "get_time", "arguments": {}})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    with sqlite3.connect(settings.audit_db) as conn:
        row = conn.execute(
            "SELECT error_code FROM audit_log WHERE action = 'get_time' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == "timeout"


def test_local_token_required_when_configured(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, token="local-token")
    client = TestClient(create_app(settings))

    unauthorized = client.get("/health")
    authorized = client.get("/health", headers={"X-Jarvis-Token": "local-token"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_no_credentials_in_logs(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))
    secret_value = "******"

    pending = client.post(
        "/action",
        json={
            "action": "create_note",
            "arguments": {"directory": ".", "filename": "safe.txt", "content": secret_value},
        },
    ).json()
    client.post(
        f"/confirm/{pending['result']['request_id']}",
        json={"token": pending["result"]["confirmation_token"]},
    )

    with sqlite3.connect(settings.audit_db) as conn:
        logs = conn.execute(
            "SELECT COALESCE(error_message, '') FROM audit_log"
        ).fetchall()

    assert all(secret_value not in row[0] for row in logs)


def test_no_shell_endpoint_when_disabled(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))

    response = client.post("/shell", json={"command": "echo hi"})

    assert response.status_code == 404


def test_reminder_is_persisted_and_delivered_once(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))
    remind_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    pending = client.post(
        "/action",
        json={"action": "create_reminder", "arguments": {"title": "Llamar a mamá", "remind_at": remind_at}},
    ).json()

    assert pending["ok"] is True
    reminder_id = pending["result"]["id"]
    assert client.get("/reminders/due").json()["reminders"] == []
    with sqlite3.connect(settings.audit_db) as conn:
        conn.execute(
            "UPDATE reminders SET remind_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), reminder_id),
        )

    first = client.get("/reminders/due").json()["reminders"]
    assert len(first) == 1
    assert client.post(f"/reminders/{reminder_id}/delivered").json()["ok"] is True
    assert client.get("/reminders/due").json()["reminders"] == []


def test_reminder_accepts_local_naive_iso_datetime(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    client = TestClient(create_app(settings))
    remind_at = (datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)).isoformat()

    response = client.post(
        "/action",
        json={"action": "create_reminder", "arguments": {"title": "Sin zona", "remind_at": remind_at}},
    )

    assert response.json()["ok"] is True
    assert response.json()["result"]["title"] == "Sin zona"
