from __future__ import annotations

import os
import re
import sqlite3
import secrets
from datetime import datetime
from typing import Any, Callable, Optional

from flask import Flask, g

DB_FILENAME = "bizflow.sqlite3"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^[0-9+()\-.\s]{0,30}$")


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config["SECRET_KEY"] = os.environ.get("BIZFLOW_SECRET_KEY") or secrets.token_hex(32)
    app.config["DATABASE"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DB_FILENAME)

    @app.before_request
    def _open_db() -> None:  # type: ignore[override]
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row

    @app.teardown_request
    def _close_db(exc: Optional[BaseException]) -> None:  # type: ignore[override]
        db = getattr(g, "db", None)
        if db is not None:
            db.close()

    init_db(app)

    from . import routes  # noqa: F401

    app.register_blueprint(routes.bp)

    return app


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_db(app: Flask) -> None:
    db_path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    db = sqlite3.connect(db_path)
    try:
        db.execute("PRAGMA foreign_keys = ON;")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS clients (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              full_name TEXT NOT NULL,
              company TEXT NOT NULL,
              phone TEXT NOT NULL DEFAULT '',
              email TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'new',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        db.commit()
    finally:
        db.close()


def validate_client_form(form: Any) -> tuple[dict[str, str], list[str]]:
    full_name = (form.get("full_name") or "").strip()
    company = (form.get("company") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip().lower()
    status = (form.get("status") or "new").strip()

    errors: list[str] = []
    if not full_name:
        errors.append("Поле «ФИО клиента» не должно быть пустым.")
    if not company:
        errors.append("Поле «Компания» не должно быть пустым.")
    if email and not EMAIL_RE.match(email):
        errors.append("Некорректный Email клиента.")
    if phone and not PHONE_RE.match(phone):
        errors.append("Телефон содержит недопустимые символы.")
    if status not in {"new", "active", "completed", "archived"}:
        errors.append("Некорректный статус.")

    return (
        {
            "full_name": full_name,
            "company": company,
            "phone": phone,
            "email": email,
            "status": status,
        },
        errors,
    )

