"""Who is allowed in: admin accounts, client sessions, and the wrong-try limits."""
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque

import psycopg
from fastapi import Header, HTTPException, Request

from sabageo.db import connect
from sabageo.helpers import sha

log = logging.getLogger("sabageo")

STAFF_HOURS = 12


# ---------- Passwords (scrypt is built into Python, so no extra library) ----------
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, n, r, p, salt, digest = stored.split("$")
        mine = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(mine.hex(), digest)


# checked when the username does not exist, so a wrong name takes as long as a wrong password
DUMMY_HASH = hash_password(secrets.token_hex(8))


def staff_tables_missing():
    raise HTTPException(status_code=503, detail="Admin accounts are not set up yet. Run phase_j.sql on this database.")


# ---------- Admin sessions (admins live in the staff table) ----------
def staff_from_token(token):
    """The logged-in admin for this token, or None."""
    if not token:
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT st.id, st.username, st.name
                FROM staff_sessions s JOIN staff st ON st.id = s.staff_id
                WHERE s.token_hash = %s AND s.expires_at > NOW() AND st.active
                """,
                (sha(token),),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        staff_tables_missing()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "name": row[2]}


def require_admin(x_staff_token: str | None = Header(default=None)):
    """Route guard: any logged-in admin may do every admin action."""
    staff = staff_from_token(x_staff_token)
    if not staff:
        raise HTTPException(status_code=401, detail="Please log in as admin first (menu → Admin login).")
    return staff


def log_action(conn, staff, action, target=None):
    """Write down which admin did what. Uses the caller's connection, so it is saved with the action itself."""
    conn.execute("INSERT INTO staff_log (staff_id, action, target) VALUES (%s, %s, %s)",
                 (staff["id"], action, target))


# ---------- Rate limits ----------
# Kept in the rate_hits table, so they survive a restart and are shared by every server.
# Without that table (phase_j.sql not run) they fall back to memory, like before.
_fails = defaultdict(deque)
_hits = defaultdict(deque)


def client_ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _count(bucket, visitor, window, memory, add_below=0):
    """Hits this visitor had in the last `window` seconds. Adds a new hit only if the count is
    under `add_below`, so a blocked request does not make the wait longer."""
    try:
        with connect() as conn:
            conn.execute(
                "DELETE FROM rate_hits WHERE bucket = %s AND visitor = %s AND hit_at < NOW() - make_interval(secs => %s)",
                (bucket, visitor, window),
            )
            n = conn.execute("SELECT COUNT(*) FROM rate_hits WHERE bucket = %s AND visitor = %s",
                             (bucket, visitor)).fetchone()[0]
            if n < add_below:
                conn.execute("INSERT INTO rate_hits (bucket, visitor) VALUES (%s, %s)", (bucket, visitor))
            return n
    except psycopg.errors.UndefinedTable:
        log.warning("rate_hits table missing: run phase_j.sql (rate limits are in memory for now)")
        q, now = memory[(bucket, visitor)], time.time()
        while q and now - q[0] > window:
            q.popleft()
        n = len(q)
        if n < add_below:
            q.append(now)
        return n


def check_limit(request: Request, limit=8, window=600):
    """Stop a visitor after too many wrong codes or passwords. record_fail counts them."""
    if _count("fail", client_ip(request), window, _fails) >= limit:
        raise HTTPException(status_code=429, detail="Too many wrong tries. Please wait ten minutes.")


def record_fail(request: Request):
    _count("fail", client_ip(request), 600, _fails, add_below=10 ** 9)


def throttle(request: Request, bucket, limit, window):
    """Allow `limit` calls per `window` seconds per visitor for this bucket, then answer 429."""
    if _count(bucket, client_ip(request), window, _hits, add_below=limit) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a few minutes and try again.")


# ---------- Client accounts (email + password, 7-day login) ----------
ACCOUNT_DAYS = 7


def account_from_token(token):
    """The logged-in client account for this token, or None."""
    if not token:
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT a.id, a.email, a.name, a.phone
                FROM account_sessions s JOIN accounts a ON a.id = s.account_id
                WHERE s.token_hash = %s AND s.expires_at > NOW() AND a.active
                """,
                (sha(token),),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        raise HTTPException(status_code=503, detail="Client accounts are not set up yet. Run phase_j.sql on this database.")
    if not row:
        return None
    return {"id": row[0], "email": row[1], "name": row[2], "phone": row[3]}


def require_account(x_account_token: str | None = Header(default=None)):
    account = account_from_token(x_account_token)
    if not account:
        raise HTTPException(status_code=401, detail="Please log in to your account.")
    return account


# ---------- Client sessions (one login code) ----------
def require_client(x_client_token: str | None = Header(default=None)):
    if not x_client_token:
        raise HTTPException(status_code=401, detail="Please log in with your login code.")
    with connect() as conn:
        row = conn.execute(
            """
            SELECT lc.id, lc.client_id, lc.plots_allowed, lc.plots_used, c.name, c.client_type, lc.expires_at,
                   c.phone, c.email
            FROM client_sessions s
            JOIN login_codes lc ON lc.id = s.code_id
            JOIN clients c ON c.id = lc.client_id
            JOIN payments p ON p.id = lc.payment_id
            WHERE s.token_hash = %s AND s.expires_at > NOW()
              AND NOT lc.revoked AND lc.expires_at > NOW() AND p.status = 'confirmed'
            """,
            (sha(x_client_token),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Your session has ended. Please log in again.")
    return {"code_id": row[0], "client_id": row[1], "plots_allowed": row[2], "plots_used": row[3],
            "name": row[4], "client_type": row[5], "code_expires": row[6].isoformat(),
            "phone": row[7], "email": row[8]}
