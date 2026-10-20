"""Client accounts, like a shop account: sign up, log in, see your receipts and plots,
start Register New Plot without typing a code, and get a fresh code yourself.
Admins see every account and can reset a password or switch an account off."""
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from sabageo import config
from sabageo.codes import replace_login_code
from sabageo.db import connect
from sabageo.helpers import clean_contact, sha
from sabageo.models import AccountLoginIn, ClaimIn, PasswordChangeIn, PasswordIn, SignupIn
from sabageo.routes.clients import open_code_session
from sabageo.security import (ACCOUNT_DAYS, DUMMY_HASH, check_limit, check_password, hash_password, log_action,
                              record_fail, require_account, require_admin, throttle)

router = APIRouter()


def accounts_missing():
    raise HTTPException(status_code=503, detail="Client accounts are not set up yet. Run phase_j.sql on this database.")


def new_session(conn, account_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=ACCOUNT_DAYS)
    conn.execute("INSERT INTO account_sessions (token_hash, account_id, expires_at) VALUES (%s, %s, %s)",
                 (sha(token), account_id, expires))
    conn.execute("DELETE FROM account_sessions WHERE account_id = %s AND expires_at < NOW()", (account_id,))
    conn.execute("UPDATE accounts SET last_login_at = NOW() WHERE id = %s", (account_id,))
    return token, expires


@router.get("/account")
def account_page():
    return FileResponse("account.html")


@router.post("/api/account/signup")
def signup(body: SignupIn, request: Request):
    throttle(request, "signup", limit=10, window=3600)
    phone, email = clean_contact(body.phone, body.email.strip().lower())
    if not email:
        raise HTTPException(status_code=400, detail="Please enter your email address.")
    try:
        with connect() as conn:
            account_id = conn.execute(
                "INSERT INTO accounts (email, name, phone, password_hash) VALUES (%s, %s, %s, %s) RETURNING id",
                (email, body.name.strip(), phone, hash_password(body.password)),
            ).fetchone()[0]
            token, expires = new_session(conn, account_id)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="There is already an account with that email. Log in instead.")
    except psycopg.errors.UndefinedTable:
        accounts_missing()
    return {"token": token, "expires_at": expires.isoformat(), "name": body.name.strip(), "email": email}


@router.post("/api/account/login")
def account_login(body: AccountLoginIn, request: Request):
    check_limit(request)
    email = body.email.strip().lower()
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT id, name, email, password_hash FROM accounts WHERE email = %s AND active", (email,)
            ).fetchone()
            # always run one hash check, so a wrong email is not quicker than a wrong password
            ok = check_password(body.password, row[3] if row else DUMMY_HASH) and row is not None
            if not ok:
                record_fail(request)
                raise HTTPException(status_code=401, detail="Wrong email or password.")
            token, expires = new_session(conn, row[0])
    except psycopg.errors.UndefinedTable:
        accounts_missing()
    return {"token": token, "expires_at": expires.isoformat(), "name": row[1], "email": row[2]}


@router.post("/api/account/logout")
def account_logout(x_account_token: str | None = Header(default=None)):
    if x_account_token:
        with connect() as conn:
            conn.execute("DELETE FROM account_sessions WHERE token_hash = %s", (sha(x_account_token),))
    return {"ok": True}


def code_state(expires, revoked, pay_status, allowed, used):
    if expires is None:
        return "none"
    if revoked or pay_status == "void":
        return "revoked"
    if expires < datetime.now(timezone.utc):
        return "expired"
    if allowed is not None and used >= allowed:
        return "used_up"
    return "active"


@router.get("/api/account/me")
def account_me(account=Depends(require_account)):
    with connect() as conn:
        pays = conn.execute(
            """
            SELECT p.receipt_no, p.verify_code, p.amount_ngn, p.method, p.status, p.created_at, c.client_type,
                   lc.expires_at, lc.plots_allowed, lc.plots_used, lc.revoked
            FROM payments p
            JOIN clients c ON c.id = p.client_id
            LEFT JOIN LATERAL (
                SELECT * FROM login_codes WHERE payment_id = p.id ORDER BY id DESC LIMIT 1
            ) lc ON TRUE
            WHERE c.account_id = %s
            ORDER BY p.id DESC
            """,
            (account["id"],),
        ).fetchall()
        plots = conn.execute(
            """
            SELECT p.title_code, r.name, p.area_m2, p.registered_at, p.owner_name
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.client_id IN (SELECT id FROM clients WHERE account_id = %s)
            ORDER BY p.id DESC
            """,
            (account["id"],),
        ).fetchall()
    return {
        **account,
        "payments": [{
            "receipt_no": r[0], "verify_code": r[1], "amount_ngn": float(r[2]), "method": r[3], "status": r[4],
            "paid_at": r[5].isoformat(), "plan": config.PLANS.get(r[6], {}).get("label", r[6]),
            "client_type": r[6], "code_state": code_state(r[7], r[10], r[4], r[8], r[9]),
            "expires_at": r[7].isoformat() if r[7] else None, "plots_allowed": r[8], "plots_used": r[9],
        } for r in pays],
        "plots": [{"title_code": r[0], "region": r[1], "area_m2": round(r[2], 1) if r[2] else None,
                   "registered_at": r[3].isoformat() if r[3] else None, "owner_name": r[4]} for r in plots],
    }


def my_payment(conn, account, receipt_no):
    """This account's payment, or a 404 (the same answer for 'no such receipt' and 'not yours')."""
    row = conn.execute(
        """
        SELECT p.id, p.status FROM payments p JOIN clients c ON c.id = p.client_id
        WHERE p.receipt_no = %s AND c.account_id = %s
        """,
        (receipt_no.strip().upper(), account["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="That receipt is not in your account.")
    if row[1] != "confirmed":
        raise HTTPException(status_code=400, detail="This payment was cancelled, so its code no longer works.")
    return row[0]


@router.post("/api/account/claim")
def claim_receipt(body: ClaimIn, request: Request, account=Depends(require_account)):
    """Add a receipt (for example one paid in cash at the office) to your account.
    The verification code printed on the receipt proves it is yours."""
    check_limit(request)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT p.verify_code, c.id, c.account_id FROM payments p JOIN clients c ON c.id = p.client_id
            WHERE p.receipt_no = %s FOR UPDATE OF c
            """,
            (body.receipt_no.strip().upper(),),
        ).fetchone()
        if not row or not secrets.compare_digest(body.verify_code.strip().upper().encode(), row[0].encode()):
            record_fail(request)
            raise HTTPException(status_code=404, detail="Receipt not found, or the verification code is wrong.")
        if row[2] is not None and row[2] != account["id"]:
            raise HTTPException(status_code=409, detail="That receipt is already in another account. Please contact SABAGeo.")
        conn.execute("UPDATE clients SET account_id = %s WHERE id = %s", (account["id"], row[1]))
    return {"ok": True}


@router.post("/api/account/payments/{receipt_no}/start")
def start_registering(receipt_no: str, account=Depends(require_account)):
    """Log in to Register New Plot with this receipt's code, without typing the code."""
    with connect() as conn:
        payment_id = my_payment(conn, account, receipt_no)
        last = conn.execute("SELECT id FROM login_codes WHERE payment_id = %s ORDER BY id DESC LIMIT 1",
                            (payment_id,)).fetchone()
        out = open_code_session(conn, "id", last[0]) if last else None
    if not out:
        raise HTTPException(status_code=400, detail="This receipt's code has expired. Make a new token payment to register more plots.")
    return out


@router.post("/api/account/payments/{receipt_no}/new-code")
def new_code(receipt_no: str, request: Request, account=Depends(require_account)):
    """A fresh login code (the old one stops working). Same expiry and plot limit: nothing extra."""
    throttle(request, "new_code", limit=10, window=3600)
    with connect() as conn:
        made = replace_login_code(conn, my_payment(conn, account, receipt_no))
    if not made:
        raise HTTPException(status_code=400, detail="This receipt's code has expired, so a new one can't be made.")
    return {"code": made[0], "expires_at": made[1].isoformat()}


@router.post("/api/account/password")
def change_password(body: PasswordChangeIn, request: Request, account=Depends(require_account),
                    x_account_token: str | None = Header(default=None)):
    check_limit(request)
    with connect() as conn:
        stored = conn.execute("SELECT password_hash FROM accounts WHERE id = %s", (account["id"],)).fetchone()[0]
        if not check_password(body.current, stored):
            record_fail(request)
            raise HTTPException(status_code=400, detail="Your current password is not right.")
        conn.execute("UPDATE accounts SET password_hash = %s WHERE id = %s", (hash_password(body.password), account["id"]))
        conn.execute("DELETE FROM account_sessions WHERE account_id = %s AND token_hash <> %s",
                     (account["id"], sha(x_account_token)))
    return {"ok": True}


# ---------- Admin: every client account ----------
@router.get("/admin/clients")
def admin_clients_page():
    return FileResponse("admin-clients.html")


@router.get("/api/admin/accounts", dependencies=[Depends(require_admin)])
def list_accounts():
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.name, a.email, a.phone, a.active, a.created_at, a.last_login_at,
                       COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'confirmed'),
                       COALESCE(SUM(p.amount_ngn) FILTER (WHERE p.status = 'confirmed'), 0),
                       (SELECT COUNT(*) FROM plots pl JOIN clients c2 ON c2.id = pl.client_id WHERE c2.account_id = a.id)
                FROM accounts a
                LEFT JOIN clients c ON c.account_id = a.id
                LEFT JOIN payments p ON p.client_id = c.id
                GROUP BY a.id ORDER BY a.id DESC LIMIT 1000
                """
            ).fetchall()
            unclaimed = conn.execute(
                "SELECT COUNT(*) FROM payments p JOIN clients c ON c.id = p.client_id WHERE c.account_id IS NULL"
            ).fetchone()[0]
    except psycopg.errors.UndefinedTable:
        accounts_missing()
    when = lambda t: t.isoformat() if t else None  # noqa: E731
    return {
        "accounts": [{"id": r[0], "name": r[1], "email": r[2], "phone": r[3], "active": r[4],
                      "created_at": when(r[5]), "last_login_at": when(r[6]),
                      "payments": r[7], "paid_ngn": float(r[8]), "plots": r[9]} for r in rows],
        "unclaimed_payments": unclaimed,
    }


def _account(conn, account_id):
    row = conn.execute("SELECT email FROM accounts WHERE id = %s", (account_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No such account.")
    return row[0]


@router.post("/api/admin/accounts/{account_id}/password")
def admin_reset_account_password(account_id: int, body: PasswordIn, staff=Depends(require_admin)):
    with connect() as conn:
        email = _account(conn, account_id)
        conn.execute("UPDATE accounts SET password_hash = %s WHERE id = %s", (hash_password(body.password), account_id))
        conn.execute("DELETE FROM account_sessions WHERE account_id = %s", (account_id,))
        log_action(conn, staff, "reset client password", email)
    return {"ok": True}


@router.post("/api/admin/accounts/{account_id}/disable")
def admin_disable_account(account_id: int, staff=Depends(require_admin)):
    with connect() as conn:
        email = _account(conn, account_id)
        conn.execute("UPDATE accounts SET active = FALSE WHERE id = %s", (account_id,))
        conn.execute("DELETE FROM account_sessions WHERE account_id = %s", (account_id,))
        log_action(conn, staff, "disabled client account", email)
    return {"ok": True}


@router.post("/api/admin/accounts/{account_id}/enable")
def admin_enable_account(account_id: int, staff=Depends(require_admin)):
    with connect() as conn:
        email = _account(conn, account_id)
        conn.execute("UPDATE accounts SET active = TRUE WHERE id = %s", (account_id,))
        log_action(conn, staff, "enabled client account", email)
    return {"ok": True}
