"""Who is allowed in: the admin key, client sessions, and the wrong-try limit."""
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from sabageo.db import connect
from sabageo.helpers import sha


# ---------- Admin lock ----------
def is_admin(key):
    expected = os.getenv("ADMIN_KEY", "")
    return bool(expected and key and secrets.compare_digest(key.encode(), expected.encode()))


def require_admin(x_admin_key: str | None = Header(default=None)):
    if not is_admin(x_admin_key):
        raise HTTPException(status_code=401, detail="Admin key needed. Open the menu and tap Admin key.")


# ---------- Wrong tries, kept in memory (resets when the server restarts) ----------
_fails = defaultdict(deque)


def client_ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def check_limit(request: Request, limit=8, window=600):
    q, now = _fails[client_ip(request)], time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="Too many wrong tries. Please wait ten minutes.")


def record_fail(request: Request):
    _fails[client_ip(request)].append(time.time())


# ---------- Busy routes: a simple per-visitor limit (in memory, like the one above) ----------
_hits = defaultdict(deque)


def throttle(request: Request, bucket, limit, window):
    """Allow `limit` calls per `window` seconds per visitor for this bucket, then answer 429."""
    q, now = _hits[(bucket, client_ip(request))], time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a few minutes and try again.")
    q.append(now)


# ---------- Client sessions ----------
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
