"""Public title check: the page a QR code on a parcel report opens."""
import io
import json

import psycopg
import segno
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from sabageo import config
from sabageo.db import connect
from sabageo.ledger import verify_chain

router = APIRouter()


def site_url(request: Request):
    return config.PUBLIC_URL or str(request.base_url).rstrip("/")


def onchain_title(conn, code):
    """The on-chain title record for this code, or None (also None before that table exists)."""
    try:
        with conn.transaction():  # a savepoint, so a missing table does not spoil the connection
            row = conn.execute(
                "SELECT record_hash, tx_hash, recorded_at FROM chain_titles WHERE title_code = %s",
                (code,),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return None
    if not row:
        return None
    return {"record_hash": row[0], "url": config.EXPLORER_TX + row[1], "recorded_at": row[2].isoformat()}


@router.get("/verify")
@router.get("/verify/{title_code}")
def verify_page(title_code: str = ""):
    return FileResponse("verify.html")


@router.get("/api/verify/{title_code}")
def verify_title(title_code: str):
    """What anyone may know about a title: is it registered, and is its record untouched?"""
    code = title_code.strip().upper()
    with connect() as conn:
        plot = conn.execute(
            """
            SELECT p.title_code, r.name, p.status, p.source, p.area_m2, p.registered_at,
                   ST_AsText(p.geom), ST_Y(ST_Centroid(p.geom)), ST_X(ST_Centroid(p.geom))
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.title_code = %s
            """,
            (code,),
        ).fetchone()
        rec = conn.execute(
            "SELECT id, payload, record_hash, created_at FROM ledger WHERE title_code = %s ORDER BY id DESC LIMIT 1",
            (code,),
        ).fetchone()
        if not plot and not rec:
            raise HTTPException(status_code=404, detail="No title with that code.")
        chain = verify_chain(conn)
        anchor = None
        if rec:
            a = conn.execute(
                "SELECT tx_hash, anchored_at FROM anchors WHERE ledger_id >= %s ORDER BY ledger_id LIMIT 1",
                (rec[0],),
            ).fetchone()
            if a:
                anchor = {"url": config.EXPLORER_TX + a[0], "anchored_at": a[1].isoformat()}
        onchain = onchain_title(conn, code)

    data = json.loads(rec[1]) if rec else {}
    if plot and plot[2] == "reserved":
        status = "reserved"
    elif plot:
        status = "registered"
    elif data.get("action") == "removed":
        status = "removed"
    else:
        status = "unknown"

    # does THIS plot still match its own latest ledger record?
    record_matches = bool(plot and rec and plot[6] and data.get("wkt") == plot[6])
    return {
        "title_code": code,
        "status": status,
        "region": plot[1] if plot else None,
        "source": plot[3] if plot else None,
        "area_m2": round(plot[4], 1) if plot and plot[4] is not None else None,
        "registered_at": plot[5].isoformat() if plot and plot[5] else None,
        "centroid": [plot[7], plot[8]] if plot and plot[7] is not None else None,
        "record": {
            "id": rec[0], "hash": rec[2], "written_at": rec[3].isoformat(),
            "matches_plot": record_matches,
            "removed_reason": data.get("reason") if data.get("action") == "removed" else None,
        } if rec else None,
        "ledger_intact": chain["valid"],
        "anchor": anchor,
        "onchain": onchain,
        "intact": status == "registered" and record_matches and chain["valid"],
    }


@router.get("/plots/{title_code}/qr.svg")
def title_qr(title_code: str, request: Request):
    code = title_code.strip().upper()
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM plots WHERE title_code = %s", (code,)).fetchone():
            raise HTTPException(status_code=404, detail="Plot not found.")
    qr = segno.make(site_url(request) + "/verify/" + code, error="m")
    out = io.BytesIO()
    qr.save(out, kind="svg", scale=4, border=2, dark="#0a1628", light="#ffffff", xmldecl=False)
    return Response(content=out.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})
