"""Admin accounts: log in, log out, change password, and manage the other admins."""
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from sabageo.db import connect
from sabageo.helpers import sha
from sabageo.models import PasswordChangeIn, PasswordIn, StaffIn, StaffLoginIn
from sabageo.security import (DUMMY_HASH, STAFF_HOURS, check_limit, check_password, hash_password,
                              log_action, record_fail, require_admin, staff_tables_missing)

router = APIRouter()


@router.get("/staff")
def staff_page():
    return FileResponse("staff.html")


@router.post("/api/staff/login")
def staff_login(body: StaffLoginIn, request: Request):
    check_limit(request)
    username = body.username.strip().lower()
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT id, username, name, password_hash FROM staff WHERE username = %s AND active",
                (username,),
            ).fetchone()
            # always run one hash check, so a wrong username is not quicker than a wrong password
            ok = check_password(body.password, row[3] if row else DUMMY_HASH) and row is not None
            if not ok:
                record_fail(request)
                raise HTTPException(status_code=401, detail="Wrong username or password.")
            token = secrets.token_urlsafe(32)
            expires = datetime.now(timezone.utc) + timedelta(hours=STAFF_HOURS)
            conn.execute("INSERT INTO staff_sessions (token_hash, staff_id, expires_at) VALUES (%s, %s, %s)",
                         (sha(token), row[0], expires))
            conn.execute("DELETE FROM staff_sessions WHERE staff_id = %s AND expires_at < NOW()", (row[0],))
            conn.execute("UPDATE staff SET last_login_at = NOW() WHERE id = %s", (row[0],))
    except psycopg.errors.UndefinedTable:
        staff_tables_missing()
    return {"token": token, "username": row[1], "name": row[2], "expires_at": expires.isoformat()}


@router.post("/api/staff/logout")
def staff_logout(x_staff_token: str | None = Header(default=None)):
    if x_staff_token:
        with connect() as conn:
            conn.execute("DELETE FROM staff_sessions WHERE token_hash = %s", (sha(x_staff_token),))
    return {"ok": True}


@router.get("/api/staff/me")
def staff_me(staff=Depends(require_admin)):
    return staff


@router.post("/api/staff/me/password")
def change_my_password(body: PasswordChangeIn, request: Request, staff=Depends(require_admin),
                       x_staff_token: str | None = Header(default=None)):
    check_limit(request)
    with connect() as conn:
        stored = conn.execute("SELECT password_hash FROM staff WHERE id = %s", (staff["id"],)).fetchone()[0]
        if not check_password(body.current, stored):
            record_fail(request)
            raise HTTPException(status_code=400, detail="Your current password is not right.")
        conn.execute("UPDATE staff SET password_hash = %s WHERE id = %s", (hash_password(body.password), staff["id"]))
        # log out every other device, keep this one
        conn.execute("DELETE FROM staff_sessions WHERE staff_id = %s AND token_hash <> %s",
                     (staff["id"], sha(x_staff_token)))
        log_action(conn, staff, "changed own password")
    return {"ok": True}


# ---------- Managing the other admins ----------
@router.get("/api/staff")
def list_staff(staff=Depends(require_admin)):
    with connect() as conn:
        people = conn.execute(
            "SELECT username, name, active, created_at, last_login_at FROM staff ORDER BY active DESC, username"
        ).fetchall()
        recent = conn.execute(
            """
            SELECT l.created_at, s.username, l.action, l.target
            FROM staff_log l JOIN staff s ON s.id = l.staff_id
            ORDER BY l.id DESC LIMIT 100
            """
        ).fetchall()
    when = lambda t: t.isoformat() if t else None  # noqa: E731
    return {
        "you": staff["username"],
        "staff": [{"username": p[0], "name": p[1], "active": p[2],
                   "created_at": when(p[3]), "last_login_at": when(p[4])} for p in people],
        "recent": [{"time": when(r[0]), "username": r[1], "action": r[2], "target": r[3]} for r in recent],
    }


@router.post("/api/staff")
def add_staff(body: StaffIn, staff=Depends(require_admin)):
    username = body.username.lower()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO staff (username, name, password_hash) VALUES (%s, %s, %s)",
                (username, body.name.strip(), hash_password(body.password)),
            )
            log_action(conn, staff, "added admin", username)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="That username is already taken.")
    return {"ok": True, "username": username}


def _target(conn, username):
    row = conn.execute("SELECT id FROM staff WHERE username = %s", (username.lower(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No admin with that username.")
    return row[0]


@router.post("/api/staff/{username}/disable")
def disable_staff(username: str, staff=Depends(require_admin)):
    # you can't disable yourself, so there is always at least one admin left
    if username.lower() == staff["username"]:
        raise HTTPException(status_code=400, detail="You can't disable your own account.")
    with connect() as conn:
        sid = _target(conn, username)
        conn.execute("UPDATE staff SET active = FALSE WHERE id = %s", (sid,))
        conn.execute("DELETE FROM staff_sessions WHERE staff_id = %s", (sid,))
        log_action(conn, staff, "disabled admin", username.lower())
    return {"ok": True}


@router.post("/api/staff/{username}/enable")
def enable_staff(username: str, staff=Depends(require_admin)):
    with connect() as conn:
        sid = _target(conn, username)
        conn.execute("UPDATE staff SET active = TRUE WHERE id = %s", (sid,))
        log_action(conn, staff, "enabled admin", username.lower())
    return {"ok": True}


@router.post("/api/staff/{username}/password")
def reset_password(username: str, body: PasswordIn, staff=Depends(require_admin)):
    """For someone who forgot theirs. Logs them out everywhere."""
    with connect() as conn:
        sid = _target(conn, username)
        conn.execute("UPDATE staff SET password_hash = %s WHERE id = %s", (hash_password(body.password), sid))
        conn.execute("DELETE FROM staff_sessions WHERE staff_id = %s", (sid,))
        log_action(conn, staff, "reset password", username.lower())
    return {"ok": True}
