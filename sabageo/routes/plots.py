"""Map data, the overlap check, registering plots and beacon photos."""
import json
import logging

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from sabageo import config
from sabageo.chain import onchain_title
from sabageo.db import connect
from sabageo.geo import find_overlaps, next_code, prepare, utm_zone
from sabageo.ledger import add_ledger_record
from sabageo.models import NewPlot
from sabageo.photos import read_upload, save_photo
from sabageo.security import require_admin

router = APIRouter()
log = logging.getLogger("sabageo")


# ---------- Map data ----------
@router.get("/regions")
def get_regions():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.code, r.name, r.is_pilot,
                   COUNT(p.id) FILTER (WHERE p.status = 'registered'),
                   COUNT(p.id) FILTER (WHERE p.status = 'reserved')
            FROM regions r LEFT JOIN plots p ON p.region_code = r.code
            GROUP BY r.code, r.name, r.is_pilot, r.sort_order
            ORDER BY r.sort_order
            """
        ).fetchall()
    return [
        {"code": r[0], "name": r[1], "is_pilot": r[2], "registered": r[3], "reserved": r[4]}
        for r in rows
    ]


@router.get("/plots")
def get_plots():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.title_code, p.region_code, p.source, p.label, ST_AsGeoJSON(p.geom),
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code),
                   p.cluster_type, p.ref_lat, p.ref_lon
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.geom IS NOT NULL
            ORDER BY r.sort_order, p.id
            """
        ).fetchall()
    features = [
        {
            "type": "Feature",
            "properties": {
                "title_code": r[0], "region": r[1], "source": r[2], "label": r[3], "photo_count": r[5],
                "cluster_type": r[6], "ref_lat": r[7], "ref_lon": r[8],
            },
            "geometry": json.loads(r[4]),
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/plots/{title_code}/coordinates")
def plot_coordinates(title_code: str, crs: str = "wgs84"):
    srid = config.CRS_CHOICES.get(crs)
    if srid is None:
        raise HTTPException(status_code=400, detail="Unknown coordinate type.")
    with connect() as conn:
        try:
            row = conn.execute(
                """
                SELECT p.title_code, p.label, p.source, r.name, p.area_m2,
                       ST_AsGeoJSON(ST_Transform(p.geom, %s::int), 8),
                       (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code),
                       p.cluster_type, p.ref_lat, p.ref_lon
                FROM plots p JOIN regions r ON r.code = p.region_code
                WHERE p.title_code = %s AND p.geom IS NOT NULL
                """,
                (srid, title_code),
            ).fetchone()
        except psycopg.Error:
            # e.g. Minna / UTM 33N before phase_h.sql has added it to this database
            raise HTTPException(status_code=400, detail="This coordinate type is not set up on the server yet.")
    if not row:
        raise HTTPException(status_code=404, detail="Plot not found.")

    ring = json.loads(row[5])["coordinates"][0][:-1]  # drop the repeated closing corner
    if crs in config.GEOGRAPHIC:
        corners = [[round(y, 6), round(x, 6)] for x, y in ring]  # latitude, longitude
    else:
        corners = [[round(x, 2), round(y, 2)] for x, y in ring]  # easting, northing
    return {
        "title_code": row[0],
        "label": row[1],
        "source": row[2],
        "region": row[3],
        "area_m2": round(row[4], 1) if row[4] is not None else None,
        "photo_count": row[6],
        "cluster_type": row[7],
        "ref": [row[8], row[9]] if row[8] is not None else None,
        "crs": crs,
        "corners": corners,
    }


@router.get("/api/registry")
def api_registry():
    # public list: no owner phone numbers or emails here
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.title_code, p.region_code, r.name, p.source, p.status, p.label,
                   p.cluster_type, p.ref_lat, p.ref_lon, p.area_m2,
                   ST_Y(ST_Centroid(p.geom)), ST_X(ST_Centroid(p.geom)),
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code),
                   p.registered_at
            FROM plots p JOIN regions r ON r.code = p.region_code
            ORDER BY r.sort_order, p.id
            """
        ).fetchall()
    keys = ["code", "region", "region_name", "source", "status", "label", "cluster_type",
            "ref_lat", "ref_lon", "area_m2", "lat", "lon", "photos", "registered_at"]
    out = []
    for row in rows:
        item = dict(zip(keys, row))
        item["registered_at"] = item["registered_at"].isoformat() if item["registered_at"] else None
        out.append(item)
    return out


@router.get("/plots/{title_code}/report")
def plot_report(title_code: str):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT p.title_code, p.label, p.source, p.cluster_type, r.name, p.area_m2,
                   ST_Perimeter(p.geom::geography),
                   ST_Y(ST_Centroid(p.geom)), ST_X(ST_Centroid(p.geom)),
                   ST_AsGeoJSON(p.geom, 8), p.registered_at,
                   p.owner_name, p.owner_type
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.title_code = %s AND p.geom IS NOT NULL
            """,
            (title_code,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Plot not found.")

        lat, lon = row[7], row[8]
        utm = utm_zone(lon)  # the plot's own UTM zone
        ring_utm = json.loads(
            conn.execute(
                "SELECT ST_AsGeoJSON(ST_Transform(geom, %s::int), 8) FROM plots WHERE title_code = %s",
                (utm, title_code),
            ).fetchone()[0]
        )["coordinates"][0][:-1]
        geometry = json.loads(row[9])
        ring_wgs = geometry["coordinates"][0][:-1]

        photos = conn.execute(
            "SELECT id, distance_m FROM photos WHERE title_code = %s AND data IS NOT NULL ORDER BY id",
            (title_code,),
        ).fetchall()

        ledger = anchor = None
        rec = conn.execute(
            "SELECT id, record_hash, created_at FROM ledger WHERE title_code = %s ORDER BY id DESC LIMIT 1",
            (title_code,),
        ).fetchone()
        if rec:
            ledger = {"record_id": rec[0], "hash": rec[1], "recorded_at": rec[2].isoformat()}
            a = conn.execute(
                "SELECT tx_hash, anchored_at FROM anchors WHERE ledger_id >= %s ORDER BY ledger_id LIMIT 1",
                (rec[0],),
            ).fetchone()
            if a:
                anchor = {"url": config.EXPLORER_TX + a[0], "anchored_at": a[1].isoformat()}
        onchain = onchain_title(conn, title_code)

    return {
        "title_code": row[0],
        "label": row[1],
        "source": row[2],
        "cluster_type": row[3],
        "region": row[4],
        "area_m2": row[5],
        "perimeter_m": row[6],
        "centroid": [lat, lon],
        "utm_zone": f"{utm - 32600}N",
        "utm_epsg": utm,
        "geometry": geometry,
        "corners_wgs": [[round(y, 6), round(x, 6)] for x, y in ring_wgs],  # latitude, longitude
        "corners_utm": [[round(x, 2), round(y, 2)] for x, y in ring_utm],  # easting, northing
        "registered_at": row[10].isoformat() if row[10] else None,
        "owner_name": row[11],  # name only; phone and email are never shown publicly
        "owner_type": row[12],
        "photos": [{"id": p[0], "distance_m": p[1]} for p in photos],
        "ledger": ledger,
        "anchor": anchor,
        "onchain": onchain,
    }


# ---------- Check and register ----------
def log_check(conn, region, hits):
    """Count the check for the admin dashboard. Never blocks the check itself."""
    try:
        with conn.transaction():  # a savepoint: a problem here cannot undo anything else
            conn.execute(
                "INSERT INTO check_log (region_code, status, overlap_count, overlap_m2) VALUES (%s, %s, %s, %s)",
                (region[:10], "RED FLAG" if hits else "0 OVERLAP", len(hits),
                 round(sum(h["overlap_m2"] for h in hits), 2)),
            )
    except psycopg.errors.UndefinedTable:
        log.warning("check_log table is missing: run phase_h.sql to turn on check counting")


@router.post("/check")
def check_overlap(plot: NewPlot):
    with connect() as conn:
        info = prepare(conn, plot)
        hits = find_overlaps(conn, info["wkt"], info["utm"])
        log_check(conn, plot.region, hits)
    base = {"shape": info["shape"], "area_m2": round(info["area"], 2)}
    if hits:
        return {
            "status": "RED FLAG",
            **base,
            "overlaps": hits,
            "total_overlap_m2": round(sum(h["overlap_m2"] for h in hits), 2),
        }
    return {"status": "0 OVERLAP", **base}


@router.post("/register", dependencies=[Depends(require_admin)])
def register_plot(plot: NewPlot):
    with connect() as conn:
        # lock so two people can't register overlapping plots at the same moment
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")

        region = conn.execute("SELECT is_pilot FROM regions WHERE code = %s", (plot.region,)).fetchone()
        if not region:
            raise HTTPException(status_code=400, detail="Unknown region.")

        info = prepare(conn, plot)
        if find_overlaps(conn, info["wkt"], info["utm"]):
            raise HTTPException(status_code=409, detail="This plot overlaps a registered plot. Not saved.")

        if region[0]:
            # pilot region: fill the next reserved slot (SABA-NAUB-RES-001 to 005, in order)
            slot = conn.execute(
                "SELECT id FROM plots WHERE region_code = %s AND status = 'reserved' ORDER BY id LIMIT 1",
                (plot.region,),
            ).fetchone()
            if not slot:
                raise HTTPException(status_code=409, detail="All pilot slots are already filled.")
            code, area, wkt = conn.execute(
                """
                UPDATE plots SET geom = ST_GeomFromText(%s, 4326), area_m2 = %s,
                                 status = 'registered', source = 'field', registered_at = NOW()
                WHERE id = %s
                RETURNING title_code, area_m2, ST_AsText(geom)
                """,
                (info["wkt"], info["area"], slot[0]),
            ).fetchone()
        else:
            code, area, wkt = conn.execute(
                """
                INSERT INTO plots (title_code, region_code, source, status, geom, area_m2)
                VALUES (%s, %s, 'field', 'registered', ST_GeomFromText(%s, 4326), %s)
                RETURNING title_code, area_m2, ST_AsText(geom)
                """,
                (next_code(conn, plot.region, "RES"), plot.region, info["wkt"], info["area"]),
            ).fetchone()

        add_ledger_record(conn, code, wkt, area)

    return {"status": "REGISTERED", "title_code": code, "area_m2": round(area, 2), "region": plot.region}


# ---------- Beacon photos (kept inside the database) ----------
@router.post("/plots/{title_code}/photo", dependencies=[Depends(require_admin)])
async def upload_photo(title_code: str, file: UploadFile = File(...)):
    data = await read_upload(file)
    with connect() as conn:
        return save_photo(conn, title_code, data)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int):
    with connect() as conn:
        row = conn.execute("SELECT data, content_type FROM photos WHERE id = %s", (photo_id,)).fetchone()
    if not row or row[0] is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    return Response(
        content=bytes(row[0]),
        media_type=row[1] or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
