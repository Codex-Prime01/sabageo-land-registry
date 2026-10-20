"""Clients: log in with a code, then register plots (Register New Plot)."""
import logging
import secrets

import psycopg

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from sabageo.codes import code_hash
from sabageo.db import connect
from sabageo.geo import find_overlaps, next_code, prepare, same_parcel
from sabageo.helpers import clean_contact, sha
from sabageo.ledger import add_ledger_record
from sabageo.models import ClientPlot, LoginIn, NewPlot
from sabageo.photos import read_upload, save_photo
from sabageo.security import check_limit, record_fail, require_client

router = APIRouter()
log = logging.getLogger("sabageo")

ONE_PLOT_REFUSAL = ("This login code is for one plot only, and it is already used for the plot you first "
                    "checked. Get a new code to check another plot.")


def enforce_one_plot(conn, client, info):
    """
    Single-plot codes (every Individual code): lock the code to the first plot it checks or
    registers, and refuse any other plot. Call inside the request's transaction, before
    answering: the code row stays locked until the transaction ends, so two tabs at once
    cannot each claim a different plot.
    """
    if client["plots_allowed"] != 1:
        return  # Corporate and multi-plot codes are not locked
    try:
        with conn.transaction():
            row = conn.execute(
                "SELECT bound_wkt FROM login_codes WHERE id = %s FOR UPDATE", (client["code_id"],)
            ).fetchone()
    except psycopg.errors.UndefinedColumn:
        log.warning("login_codes.bound_wkt is missing: run phase_i.sql to lock Individual codes to one plot")
        return
    if row[0] is None:
        conn.execute(
            "UPDATE login_codes SET bound_wkt = %s, bound_at = NOW() WHERE id = %s",
            (info["wkt"], client["code_id"]),
        )
    elif not same_parcel(conn, row[0], info["wkt"], info["utm"]):
        raise HTTPException(status_code=403, detail=ONE_PLOT_REFUSAL)


def plot_locked(conn, code_id):
    """Has this code already been locked to a plot? (False on a database without phase_i.sql.)"""
    try:
        with conn.transaction():
            row = conn.execute("SELECT bound_wkt IS NOT NULL FROM login_codes WHERE id = %s", (code_id,)).fetchone()
    except psycopg.errors.UndefinedColumn:
        return False
    return bool(row and row[0])

MAX_CLIENT_PHOTOS = 5  # per plot, to keep the free database small


def open_code_session(conn, where, value):
    """Start a Register New Plot session for one live login code (found by its hash or its id).
    Returns the answer for the browser, or None if the code is not live."""
    assert where in ("code_hash", "id")  # a column name goes into the SQL, so only these two
    row = conn.execute(
        f"""
        SELECT lc.id, lc.expires_at, lc.plots_allowed, lc.plots_used, c.name, c.client_type, c.phone, c.email
        FROM login_codes lc
        JOIN clients c ON c.id = lc.client_id
        JOIN payments p ON p.id = lc.payment_id
        WHERE lc.{where} = %s AND NOT lc.revoked AND lc.expires_at > NOW() AND p.status = 'confirmed'
        """,
        (value,),
    ).fetchone()
    if not row:
        return None
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
        "phone": row[6], "email": row[7], "one_plot": row[2] == 1,
    }


@router.post("/api/client/login")
def client_login(body: LoginIn, request: Request):
    check_limit(request)
    with connect() as conn:
        out = open_code_session(conn, "code_hash", code_hash(body.code))
    if not out:
        record_fail(request)
        raise HTTPException(status_code=401, detail="That login code is not valid or has expired.")
    return out


@router.get("/api/client/me")
def client_me(client=Depends(require_client)):
    with connect() as conn:
        locked = plot_locked(conn, client["code_id"])
    return {**client, "one_plot": client["plots_allowed"] == 1, "locked_plot": locked}


@router.post("/client/check")
def client_check(plot: NewPlot, client=Depends(require_client)):
    """The overlap check for logged-in clients. An Individual code is locked to the first plot it checks."""
    from sabageo.routes.plots import log_check  # the same check counter as the public /check
    with connect() as conn:
        info = prepare(conn, plot)
        enforce_one_plot(conn, client, info)
        hits = find_overlaps(conn, info["wkt"], info["utm"])
        log_check(conn, plot.region, hits)
    base = {"shape": info["shape"], "area_m2": round(info["area"], 2)}
    if hits:
        return {"status": "RED FLAG", **base, "overlaps": hits,
                "total_overlap_m2": round(sum(h["overlap_m2"] for h in hits), 2)}
    return {"status": "0 OVERLAP", **base}


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
        enforce_one_plot(conn, client, info)  # registering cannot sidestep the one-plot rule
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
            SELECT p.title_code, r.name, p.area_m2, p.registered_at, p.owner_name, p.owner_type,
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code)
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.client_id = %s ORDER BY p.id DESC
            """,
            (client["client_id"],),
        ).fetchall()
    return [
        {"code": r[0], "region": r[1], "area_m2": r[2],
         "registered_at": r[3].isoformat() if r[3] else None,
         "owner_name": r[4], "owner_type": r[5], "photos": r[6], "photos_left": max(0, MAX_CLIENT_PHOTOS - r[6])}
        for r in rows
    ]


@router.post("/client/plots/{title_code}/photo")
async def client_photo(title_code: str, file: UploadFile = File(...), client=Depends(require_client)):
    """A client adds a beacon photo to one of THEIR OWN plots. The GPS check runs as for the admin."""
    data = await read_upload(file)
    with connect() as conn:
        # lock the plot row, so two uploads at once cannot get past the photo limit
        owner_row = conn.execute(
            "SELECT client_id FROM plots WHERE title_code = %s FOR UPDATE", (title_code,)
        ).fetchone()
        if not owner_row or owner_row[0] != client["client_id"]:
            # the same answer for "no such plot" and "not yours", so codes cannot be probed
            raise HTTPException(status_code=404, detail="That plot is not one of yours.")
        count = conn.execute("SELECT COUNT(*) FROM photos WHERE title_code = %s", (title_code,)).fetchone()[0]
        if count >= MAX_CLIENT_PHOTOS:
            raise HTTPException(status_code=400, detail=f"This plot already has {MAX_CLIENT_PHOTOS} photos, the most allowed.")
        return save_photo(conn, title_code, data)
