"""Clients: log in with a code, then register plots (Register New Plot)."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from sabageo.codes import code_hash
from sabageo.db import connect
from sabageo.geo import find_overlaps, next_code, prepare
from sabageo.helpers import clean_contact, sha
from sabageo.ledger import add_ledger_record
from sabageo.models import ClientPlot, LoginIn
from sabageo.security import check_limit, record_fail, require_client

router = APIRouter()


@router.post("/api/client/login")
def client_login(body: LoginIn, request: Request):
    check_limit(request)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT lc.id, lc.expires_at, lc.plots_allowed, lc.plots_used, c.name, c.client_type, c.phone, c.email
            FROM login_codes lc
            JOIN clients c ON c.id = lc.client_id
            JOIN payments p ON p.id = lc.payment_id
            WHERE lc.code_hash = %s AND NOT lc.revoked AND lc.expires_at > NOW() AND p.status = 'confirmed'
            """,
            (code_hash(body.code),),
        ).fetchone()
        if not row:
            record_fail(request)
            raise HTTPException(status_code=401, detail="That login code is not valid or has expired.")
        token = secrets.token_urlsafe(32)
        ends = conn.execute("SELECT LEAST(%s::timestamptz, NOW() + interval '12 hours')", (row[1],)).fetchone()[0]
        conn.execute(
            "INSERT INTO client_sessions (token_hash, code_id, expires_at) VALUES (%s, %s, %s)",
            (sha(token), row[0], ends),
        )
        conn.execute("DELETE FROM client_sessions WHERE expires_at < NOW()")
    return {
        "token": token, "session_ends": ends.isoformat(), "name": row[4], "client_type": row[5],
        "plots_allowed": row[2], "plots_used": row[3], "code_expires": row[1].isoformat(),
        "phone": row[6], "email": row[7],
    }


@router.get("/api/client/me")
def client_me(client=Depends(require_client)):
    return client


@router.post("/client/register")
def client_register(plot: ClientPlot, client=Depends(require_client)):
    phone, email = clean_contact(plot.owner_phone, plot.owner_email)
    if not phone:
        raise HTTPException(status_code=400, detail="Please enter the owner's phone number.")
    with connect() as conn:
        # lock so two registrations can't overlap each other at the same moment
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")

        region = conn.execute("SELECT is_pilot FROM regions WHERE code = %s", (plot.region,)).fetchone()
        if not region or region[0] or plot.region == "TST":
            raise HTTPException(status_code=400, detail="Please choose one of the listed regions.")

        # read the latest plot count while holding the lock, so the limit cannot be beaten
        limits = conn.execute(
            "SELECT plots_used, plots_allowed FROM login_codes WHERE id = %s FOR UPDATE", (client["code_id"],)
        ).fetchone()
        if limits[1] is not None and limits[0] >= limits[1]:
            raise HTTPException(
                status_code=403,
                detail="This login code has no plots left. Please make a new token payment to get another code.",
            )

        info = prepare(conn, plot)
        if find_overlaps(conn, info["wkt"], info["utm"]):
            raise HTTPException(status_code=409, detail="This plot overlaps a registered plot. Not saved.")

        code, area, wkt = conn.execute(
            """
            INSERT INTO plots (title_code, region_code, source, status, geom, area_m2, client_id,
                               owner_type, owner_name, owner_phone, owner_email)
            VALUES (%s, %s, 'field', 'registered', ST_GeomFromText(%s, 4326), %s, %s, %s, %s, %s, %s)
            RETURNING title_code, area_m2, ST_AsText(geom)
            """,
            (next_code(conn, plot.region, "CLT"), plot.region, info["wkt"], info["area"], client["client_id"],
             plot.owner_type, plot.owner_name.strip(), phone, email),
        ).fetchone()
        conn.execute("UPDATE login_codes SET plots_used = plots_used + 1 WHERE id = %s", (client["code_id"],))
        add_ledger_record(conn, code, wkt, area)

    return {"status": "REGISTERED", "title_code": code, "area_m2": round(area, 2), "region": plot.region}


@router.get("/api/client/plots")
def client_plots(client=Depends(require_client)):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.title_code, r.name, p.area_m2, p.registered_at, p.owner_name, p.owner_type
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.client_id = %s ORDER BY p.id DESC
            """,
            (client["client_id"],),
        ).fetchall()
    return [
        {"code": r[0], "region": r[1], "area_m2": r[2],
         "registered_at": r[3].isoformat() if r[3] else None,
         "owner_name": r[4], "owner_type": r[5]}
        for r in rows
    ]
