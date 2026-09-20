from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock


class AuditLogger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    action TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    error_code TEXT,
                    error_message TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def log(
        self,
        *,
        action: str,
        risk: str,
        ok: bool,
        duration_ms: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        safe_message = (error_message or "")[:300]
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                    INSERT INTO audit_log(action, risk, ok, duration_ms, error_code, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                (action, risk, 1 if ok else 0, duration_ms, error_code, safe_message or None),
            )
