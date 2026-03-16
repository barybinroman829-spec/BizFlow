from __future__ import annotations

import sqlite3
from functools import wraps
from typing import Any, Callable, Optional

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import EMAIL_RE, PHONE_RE, now_iso, validate_client_form

bp = Blueprint("main", __name__)
APP_NAME = "BizFlow"


def current_user() -> Optional[sqlite3.Row]:
    uid = session.get("user_id")
    if not uid:
        return None
    return g.db.execute("SELECT id, email, created_at FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("user_id"):
            flash("Пожалуйста, войдите в систему.", "error")
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.app_errorhandler(400)
@bp.app_errorhandler(401)
@bp.app_errorhandler(403)
@bp.app_errorhandler(404)
@bp.app_errorhandler(500)
def handle_error(err):  # type: ignore[override]
    code = getattr(err, "code", 500)
    return (
        render_template(
            "error.html",
            code=code,
            app_name=APP_NAME,
        ),
        code,
    )


@bp.get("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return render_template("public_home.html", app_name=APP_NAME)


@bp.get("/register")
def register():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html", app_name=APP_NAME)


@bp.post("/register")
def register_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""

    errors: list[str] = []
    if not email:
        errors.append("Email не должен быть пустым.")
    elif not EMAIL_RE.match(email):
        errors.append("Некорректный Email.")
    if not password:
        errors.append("Пароль не должен быть пустым.")
    elif len(password) < 6:
        errors.append("Пароль должен быть не короче 6 символов.")
    if password != password2:
        errors.append("Пароли не совпадают.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("main.register"))

    try:
        g.db.execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES(?,?,?)",
            (email, generate_password_hash(password), now_iso()),
        )
        g.db.commit()
    except sqlite3.IntegrityError:
        flash("Пользователь с таким Email уже существует.", "error")
        return redirect(url_for("main.register"))

    flash("Аккаунт создан. Теперь войдите.", "success")
    return redirect(url_for("main.login"))


@bp.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    next_url = request.args.get("next") or ""
    return render_template("auth/login.html", next_url=next_url, app_name=APP_NAME)


@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or ""

    if not email or not password:
        flash("Введите Email и пароль.", "error")
        return redirect(url_for("main.login", next=next_url))

    row = g.db.execute(
        "SELECT id, email, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()

    if not row or not check_password_hash(row["password_hash"], password):
        flash("Неверный Email или пароль.", "error")
        return redirect(url_for("main.login", next=next_url))

    session["user_id"] = int(row["id"])
    flash("Вы вошли в систему.", "success")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("main.dashboard"))


@bp.post("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "success")
    return redirect(url_for("main.index"))


@bp.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    assert user is not None

    total = g.db.execute(
        "SELECT COUNT(*) AS c FROM clients WHERE user_id = ?",
        (user["id"],),
    ).fetchone()["c"]
    active = g.db.execute(
        "SELECT COUNT(*) AS c FROM clients WHERE user_id = ? AND status = 'active'",
        (user["id"],),
    ).fetchone()["c"]
    new = g.db.execute(
        "SELECT COUNT(*) AS c FROM clients WHERE user_id = ? AND status = 'new'",
        (user["id"],),
    ).fetchone()["c"]
    recent = g.db.execute(
        "SELECT id, full_name, company, status, created_at FROM clients WHERE user_id = ? ORDER BY id DESC LIMIT 5",
        (user["id"],),
    ).fetchall()

    return render_template(
        "dashboard.html",
        app_name=APP_NAME,
        user=user,
        total=total,
        active=active,
        new=new,
        recent=recent,
        active_nav="dashboard",
    )


@bp.get("/clients")
@login_required
def clients():
    user = current_user()
    assert user is not None

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip()

    params: list[Any] = [user["id"]]
    where = "WHERE user_id = ?"
    if q:
        where += " AND (LOWER(full_name) LIKE ? OR LOWER(company) LIKE ? OR LOWER(email) LIKE ?)"
        like = f"%{q.lower()}%"
        params.extend([like, like, like])
    if status and status != "all":
        where += " AND status = ?"
        params.append(status)

    rows = g.db.execute(
        f"""
        SELECT id, full_name, company, phone, email, status, created_at
        FROM clients
        {where}
        ORDER BY id DESC
        """,
        tuple(params),
    ).fetchall()

    return render_template(
        "clients/list.html",
        app_name=APP_NAME,
        user=user,
        rows=rows,
        q=q,
        status=status,
        active_nav="clients",
    )


@bp.get("/clients/new")
@login_required
def client_new():
    user = current_user()
    assert user is not None
    return render_template(
        "clients/form.html",
        app_name=APP_NAME,
        user=user,
        client=None,
        active_nav="clients",
    )


@bp.post("/clients/new")
@login_required
def client_new_post():
    user = current_user()
    assert user is not None

    data, errors = validate_client_form(request.form)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("main.client_new"))

    g.db.execute(
        """
        INSERT INTO clients(user_id, full_name, company, phone, email, status, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            user["id"],
            data["full_name"],
            data["company"],
            data["phone"],
            data["email"],
            data["status"],
            now_iso(),
            now_iso(),
        ),
    )
    g.db.commit()
    flash("Клиент добавлен.", "success")
    return redirect(url_for("main.clients"))


@bp.get("/clients/<int:client_id>/edit")
@login_required
def client_edit(client_id: int):
    user = current_user()
    assert user is not None

    row = g.db.execute(
        "SELECT * FROM clients WHERE id = ? AND user_id = ?",
        (client_id, user["id"]),
    ).fetchone()
    if not row:
        abort(404)

    return render_template(
        "clients/form.html",
        app_name=APP_NAME,
        user=user,
        client=row,
        active_nav="clients",
    )


@bp.post("/clients/<int:client_id>/edit")
@login_required
def client_edit_post(client_id: int):
    user = current_user()
    assert user is not None

    exists = g.db.execute(
        "SELECT id FROM clients WHERE id = ? AND user_id = ?",
        (client_id, user["id"]),
    ).fetchone()
    if not exists:
        abort(404)

    data, errors = validate_client_form(request.form)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("main.client_edit", client_id=client_id))

    g.db.execute(
        """
        UPDATE clients
           SET full_name = ?, company = ?, phone = ?, email = ?, status = ?, updated_at = ?
         WHERE id = ? AND user_id = ?
        """,
        (
            data["full_name"],
            data["company"],
            data["phone"],
            data["email"],
            data["status"],
            now_iso(),
            client_id,
            user["id"],
        ),
    )
    g.db.commit()
    flash("Изменения сохранены.", "success")
    return redirect(url_for("main.clients"))


@bp.post("/clients/<int:client_id>/delete")
@login_required
def client_delete(client_id: int):
    user = current_user()
    assert user is not None

    g.db.execute("DELETE FROM clients WHERE id = ? AND user_id = ?", (client_id, user["id"]))
    g.db.commit()
    flash("Клиент удалён.", "success")
    return redirect(url_for("main.clients"))


@bp.get("/docs")
def docs():
    user = current_user()
    return render_template(
        "docs.html",
        app_name=APP_NAME,
        user=user,
        active_nav="docs" if user else "",
    )

