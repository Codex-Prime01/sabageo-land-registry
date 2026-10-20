"""Token payments, login codes and receipts."""
import secrets
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from sabageo import config
from sabageo.codes import create_payment, issue_login_code
from sabageo.db import connect
from sabageo.helpers import clean_contact
from sabageo.models import PaymentIn, ReissueIn
from sabageo.security import check_limit, log_action, record_fail, require_admin, staff_from_token

router = APIRouter()


@router.get("/api/prices")
def prices():
    """Public price list for the Token payment page."""
    return {"plans": config.PLANS, "provisional": True, "currency": "NGN"}


@router.post("/api/admin/payments")
def record_payment(p: PaymentIn, staff=Depends(require_admin)):
    phone, email = clean_contact(p.phone, p.email)
    try:
        with connect() as conn:
            out = create_payment(conn, p.name, p.client_type, email, phone, p.amount_ngn, p.method,
                                 p.reference, p.valid_days, p.plots_allowed)
            log_action(conn, staff, "recorded payment", out.get("receipt_no"))
            return out
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="That payment reference has already been recorded.")


@router.get("/api/admin/payments", dependencies=[Depends(require_admin)])
def list_payments():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.receipt_no, p.verify_code, p.amount_ngn, p.method, p.reference, p.status, p.created_at,
                   c.name, c.client_type, c.email, c.phone,
                   lc.expires_at, lc.plots_allowed, lc.plots_used, lc.revoked
            FROM payments p
            JOIN clients c ON c.id = p.client_id
            LEFT JOIN LATERAL (
                SELECT * FROM login_codes WHERE payment_id = p.id ORDER BY id DESC LIMIT 1
            ) lc ON TRUE
            ORDER BY p.id DESC LIMIT 500
            """
        ).fetchall()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        if r[11] is None:
            state = "none"
        elif r[14] or r[5] == "void":
            state = "revoked"
        elif r[11] < now:
            state = "expired"
        else:
            state = "active"
        out.append({
            "receipt_no": r[0], "verify_code": r[1], "amount_ngn": float(r[2]), "method": r[3],
            "reference": r[4], "status": r[5], "created_at": r[6].isoformat(),
            "name": r[7], "client_type": r[8], "email": r[9], "phone": r[10],
            "code_state": state, "expires_at": r[11].isoformat() if r[11] else None,
            "plots_allowed": r[12], "plots_used": r[13],
        })
    return out


@router.post("/api/admin/payments/{receipt_no}/void")
def void_payment(receipt_no: str, staff=Depends(require_admin)):
    with connect() as conn:
        row = conn.execute("UPDATE payments SET status = 'void' WHERE receipt_no = %s RETURNING id", (receipt_no,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        conn.execute("UPDATE login_codes SET revoked = TRUE WHERE payment_id = %s", (row[0],))
        conn.execute(
            "DELETE FROM client_sessions WHERE code_id IN (SELECT id FROM login_codes WHERE payment_id = %s)",
            (row[0],),
        )
        log_action(conn, staff, "voided payment", receipt_no)
    return {"ok": True}


@router.post("/api/admin/payments/{receipt_no}/reissue")
def reissue_code(receipt_no: str, body: ReissueIn | None = None, staff=Depends(require_admin)):
    days = body.valid_days if body else 30
    with connect() as conn:
        pay = conn.execute(
            "SELECT id, client_id, status FROM payments WHERE receipt_no = %s", (receipt_no,)
        ).fetchone()
        if not pay:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        if pay[2] != "confirmed":
            raise HTTPException(status_code=400, detail="This payment is void.")
        last = conn.execute(
            "SELECT plots_allowed, plots_used FROM login_codes WHERE payment_id = %s ORDER BY id DESC LIMIT 1",
            (pay[0],),
        ).fetchone()
        conn.execute("UPDATE login_codes SET revoked = TRUE WHERE payment_id = %s", (pay[0],))
        conn.execute(
            "DELETE FROM client_sessions WHERE code_id IN (SELECT id FROM login_codes WHERE payment_id = %s)",
            (pay[0],),
        )
        code, expires = issue_login_code(conn, pay[0], pay[1], days, last[0] if last else None, last[1] if last else 0)
        log_action(conn, staff, "issued new code", receipt_no)
    return {"code": code, "expires_at": expires.isoformat()}


@router.post("/api/admin/payments/{receipt_no}/unlock-plot")
def unlock_plot(receipt_no: str, staff=Depends(require_admin)):
    """For a genuine mistake (e.g. a big typo in the corners): free the code to check a plot again.
    Its plot limit and expiry stay the same."""
    with connect() as conn:
        pay = conn.execute("SELECT id FROM payments WHERE receipt_no = %s", (receipt_no,)).fetchone()
        if not pay:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        try:
            row = conn.execute(
                """
                UPDATE login_codes SET bound_wkt = NULL, bound_at = NULL
                WHERE id = (SELECT id FROM login_codes WHERE payment_id = %s ORDER BY id DESC LIMIT 1)
                RETURNING id
                """,
                (pay[0],),
            ).fetchone()
        except psycopg.errors.UndefinedColumn:
            raise HTTPException(status_code=503, detail="Run phase_i.sql on this database first.")
        if not row:
            raise HTTPException(status_code=404, detail="This payment has no login code.")
        log_action(conn, staff, "unlocked plot", receipt_no)
    return {"ok": True}


@router.get("/api/receipts/{receipt_no}")
def get_receipt(receipt_no: str, request: Request, v: str = "", x_staff_token: str | None = Header(default=None)):
    """Public, but you need the verification code printed on the receipt."""
    # admins can open any receipt without its verification code
    admin = bool(staff_from_token(x_staff_token))
    if not admin:
        check_limit(request)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT p.receipt_no, p.verify_code, p.amount_ngn, p.method, p.reference, p.status, p.created_at,
                   c.name, c.client_type, lc.expires_at, lc.plots_allowed
            FROM payments p JOIN clients c ON c.id = p.client_id
            LEFT JOIN LATERAL (
                SELECT expires_at, plots_allowed FROM login_codes
                WHERE payment_id = p.id ORDER BY id DESC LIMIT 1
            ) lc ON TRUE
            WHERE p.receipt_no = %s
            """,
            (receipt_no.strip().upper(),),
        ).fetchone()
    good = bool(row) and (admin or secrets.compare_digest(v.strip().upper().encode(), row[1].encode()))
    if not good:
        if not admin:
            record_fail(request)
        raise HTTPException(status_code=404, detail="Receipt not found, or the verification code is wrong.")
    plan = config.PLANS.get(row[8], {})
    return {
        "receipt_no": row[0], "verify_code": row[1],
        "valid": row[5] == "confirmed", "status": row[5],
        "amount_ngn": float(row[2]), "method": row[3], "reference": row[4],
        "issued_at": row[6].isoformat(), "name": row[7], "client_type": row[8],
        "plan": (plan.get("label", "") + ", " + plan.get("per", "")).strip(", "),
        "code_expires": row[9].isoformat() if row[9] else None,
        "plots_allowed": row[10],
    }
