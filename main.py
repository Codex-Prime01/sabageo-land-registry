import re
import time
from collections import defaultdict, deque
from typing import Literal

import base64
import hashlib
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timezone

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, Field
from web3 import Web3

load_dotenv(override=True)

# DATABASE_URL is used when hosted online. Locally we use the .env values.
DB = os.getenv("DATABASE_URL") or make_conninfo(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "sabageo"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", ""),
)

MAX_PHOTO_BYTES = 10 * 1024 * 1024

# Coordinate types the website can send. Plots are always STORED as WGS84 (EPSG:4326).
CRS_CHOICES = {"wgs84": 4326, "utm31": 32631, "utm32": 32632, "utm33": 32633}

# Rough box around Nigeria (west, south, east, north). Catches wrong-zone mistakes.
NIGERIA = (2.6, 4.2, 14.8, 13.95)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# ---------- Optional site password (keeps the project private) ----------
@app.middleware("http")
async def site_gate(request: Request, call_next):
    password = os.getenv("SITE_PASSWORD")
    if not password or request.url.path == "/health":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(given, password):
                return await call_next(request)
        except Exception:
            pass
    return PlainTextResponse(
        "Private project. Password needed.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="SABAGeo"'},
    )


# ---------- Admin lock ----------
def require_admin(x_admin_key: str | None = Header(default=None)):
    expected = os.getenv("ADMIN_KEY", "")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Admin key needed. Open the menu and tap Admin key.")


# ---------- Data shapes ----------
class Corner(BaseModel):
    easting: float   # x: easting, or LONGITUDE when the type is wgs84
    northing: float  # y: northing, or LATITUDE when the type is wgs84


class NewPlot(BaseModel):
    corners: list[Corner]
    crs: str = "utm32"     # wgs84, utm31, utm32 or utm33
    region: str = "TST"    # TST = test area. NAUB = real pilot plots (uses the reserved slots)


# ---------- Helpers ----------
def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare(conn, plot: NewPlot):
    """Turn the typed corners into a WGS84 polygon and check it makes sense."""
    if len(plot.corners) < 3:
        raise HTTPException(status_code=400, detail="A plot needs at least 3 corners")
    srid = CRS_CHOICES.get(plot.crs)
    if srid is None:
        raise HTTPException(status_code=400, detail="Unknown coordinate type.")

    pts = [(c.easting, c.northing) for c in plot.corners]
    if plot.crs == "wgs84" and any(abs(x) > 180 or abs(y) > 90 for x, y in pts):
        raise HTTPException(status_code=400, detail="Latitude must be within 90 and longitude within 180.")
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    text = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in pts) + "))"

    try:
        wkt, valid, lon, lat, area, geojson = conn.execute(
            """
            SELECT ST_AsText(g), ST_IsValid(g), ST_X(ST_Centroid(g)), ST_Y(ST_Centroid(g)),
                   ST_Area(g::geography), ST_AsGeoJSON(g)
            FROM (SELECT ST_Transform(ST_GeomFromText(%s, %s::int), 4326) AS g) t
            """,
            (text, srid),
        ).fetchone()
    except psycopg.Error:
        raise HTTPException(status_code=400, detail="Those coordinates could not be converted. Check the coordinate type.")

    if not valid:
        raise HTTPException(status_code=400, detail="Shape is invalid. Check the order of your corners.")
    west, south, east, north = NIGERIA
    if not (west <= lon <= east and south <= lat <= north):
        raise HTTPException(
            status_code=400,
            detail="These coordinates land outside Nigeria. Check the coordinate type (lat/long, or the UTM zone).",
        )
    utm = 32600 + int((lon + 180) // 6) + 1  # the local UTM zone, used to measure in metres
    return {"wkt": wkt, "shape": json.loads(geojson), "area": area, "utm": utm}


def find_overlaps(conn, wkt, utm):
    """Registered plots that share real area with this shape (touching edges do not count)."""
    return conn.execute(
        """
        WITH n AS (SELECT ST_GeomFromText(%s, 4326) AS g)
        SELECT p.title_code,
               ST_Area(ST_Intersection(ST_Transform(p.geom, %s::int), ST_Transform(n.g, %s::int))) AS overlap_m2
        FROM plots p, n
        WHERE p.geom IS NOT NULL
          AND ST_Intersects(p.geom, n.g)
          AND ST_Area(ST_Intersection(ST_Transform(p.geom, %s::int), ST_Transform(n.g, %s::int))) > 0.01
        """,
        (wkt, utm, utm, utm, utm),
    ).fetchall()


def next_code(conn, region, kind):
    n = conn.execute(
        r"""
        SELECT COALESCE(MAX(((regexp_match(title_code, '(\d+)$'))[1])::int), 0) + 1
        FROM plots WHERE region_code = %s AND title_code LIKE %s
        """,
        (region, f"SABA-{region}-{kind}-%"),
    ).fetchone()[0]
    return f"SABA-{region}-{kind}-{n:03d}"


def add_ledger_record(conn, code, wkt, area):
    """Each ledger record holds the fingerprint of the one before it."""
    last = conn.execute("SELECT record_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last[0] if last else "GENESIS"
    payload = json.dumps(
        {
            "title_code": code,
            "wkt": wkt,
            "area_m2": round(area, 2),
            "time": datetime.now(timezone.utc).isoformat(),
        },
        sort_keys=True,
    )
    conn.execute(
        "INSERT INTO ledger (title_code, payload, prev_hash, record_hash) VALUES (%s, %s, %s, %s)",
        (code, payload, prev_hash, sha(prev_hash + payload)),
    )


def read_gps(source):
    """Return (lat, lon) from the photo's GPS tag, or None if it has none."""
    try:
        gps = Image.open(source).getexif().get_ifd(0x8825)
        if not gps:
            return None

        def to_degrees(values, ref):
            d, m, s = [float(x) for x in values]
            value = d + m / 60 + s / 3600
            return -value if ref in ("S", "W") else value

        return to_degrees(gps[2], gps[1]), to_degrees(gps[4], gps[3])
    except Exception:
        return None



app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------- Pages and reading data ----------
@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/health")
def health():
    # tiny route for the keep-awake pinger; it does not touch the database
    return {"ok": True}


@app.get("/about")
def about_page():
    return FileResponse("about.html")


@app.get("/how-it-works")
def how_it_works_page():
    return FileResponse("how-it-works.html")

@app.get("/architecture")
def architecture_page():
    return FileResponse("architecture.html")


@app.get("/regions")
def get_regions():
    with psycopg.connect(DB) as conn:
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


@app.get("/plots")
def get_plots():
    with psycopg.connect(DB) as conn:
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


@app.get("/plots/{title_code}/coordinates")
def plot_coordinates(title_code: str, crs: str = "wgs84"):
    srid = CRS_CHOICES.get(crs)
    if srid is None:
        raise HTTPException(status_code=400, detail="Unknown coordinate type.")
    with psycopg.connect(DB) as conn:
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
    if not row:
        raise HTTPException(status_code=404, detail="Plot not found.")

    ring = json.loads(row[5])["coordinates"][0][:-1]  # drop the repeated closing corner
    if crs == "wgs84":
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
    
    
    
@app.get("/registry")
def registry_page():
    return FileResponse("registry.html")


@app.get("/report")
@app.get("/report/{title_code}")
def report_page(title_code: str = ""):
    return FileResponse("report.html")


@app.get("/api/registry")
def api_registry():
    with psycopg.connect(DB) as conn:
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


@app.get("/plots/{title_code}/report")
def plot_report(title_code: str):
    with psycopg.connect(DB) as conn:
        row = conn.execute(
            """
            SELECT p.title_code, p.label, p.source, p.cluster_type, r.name, p.area_m2,
                   ST_Perimeter(p.geom::geography),
                   ST_Y(ST_Centroid(p.geom)), ST_X(ST_Centroid(p.geom)),
                   ST_AsGeoJSON(p.geom, 8), p.registered_at
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.title_code = %s AND p.geom IS NOT NULL
            """,
            (title_code,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Plot not found.")

        lat, lon = row[7], row[8]
        utm = 32600 + int((lon + 180) // 6) + 1  # the plot's own UTM zone
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
                anchor = {"url": EXPLORER_TX + a[0], "anchored_at": a[1].isoformat()}

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
        "photos": [{"id": p[0], "distance_m": p[1]} for p in photos],
        "ledger": ledger,
        "anchor": anchor,
    }

# ---------- Check and register ----------
@app.post("/check")
def check_overlap(plot: NewPlot):
    with psycopg.connect(DB) as conn:
        info = prepare(conn, plot)
        rows = find_overlaps(conn, info["wkt"], info["utm"])
    if rows:
        return {
            "status": "RED FLAG",
            "shape": info["shape"],
            "overlaps": [{"title_code": r[0], "overlap_m2": round(r[1], 2)} for r in rows],
        }
    return {"status": "0 OVERLAP", "shape": info["shape"]}


@app.post("/register", dependencies=[Depends(require_admin)])
def register_plot(plot: NewPlot):
    with psycopg.connect(DB) as conn:
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
@app.post("/plots/{title_code}/photo", dependencies=[Depends(require_admin)])
async def upload_photo(title_code: str, file: UploadFile = File(...)):
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Use a JPG or PNG photo.")
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Photo is too big. Keep it under 10 MB.")

    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="That file is not a real image.")

    # read the GPS tag first, because shrinking the photo removes it
    gps = read_gps(io.BytesIO(data))

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82)
    small = out.getvalue()

    with psycopg.connect(DB) as conn:
        exists = conn.execute("SELECT 1 FROM plots WHERE title_code = %s", (title_code,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Plot not found.")

        lat = lon = distance = None
        if gps:
            lat, lon = gps
            # metres from where the photo was taken to the plot; 0 means inside it
            distance = conn.execute(
                """
                SELECT ST_Distance(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, geom::geography)
                FROM plots WHERE title_code = %s
                """,
                (lon, lat, title_code),
            ).fetchone()[0]

        photo_id = conn.execute(
            """
            INSERT INTO photos (title_code, filename, lat, lon, distance_m, data, content_type)
            VALUES (%s, %s, %s, %s, %s, %s, 'image/jpeg') RETURNING id
            """,
            (title_code, uuid.uuid4().hex + ".jpg", lat, lon, distance, small),
        ).fetchone()[0]

    return {
        "id": photo_id,
        "has_gps": gps is not None,
        "distance_m": round(distance, 1) if distance is not None else None,
    }


@app.get("/photos/{photo_id}")
def get_photo(photo_id: int):
    with psycopg.connect(DB) as conn:
        row = conn.execute("SELECT data, content_type FROM photos WHERE id = %s", (photo_id,)).fetchone()
    if not row or row[0] is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    return Response(
        content=bytes(row[0]),
        media_type=row[1] or "image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------- Ledger ----------
@app.get("/ledger/verify")
def verify_ledger():
    def broken(record_id, reason):
        return {"valid": False, "broken_at": record_id, "reason": reason}

    with psycopg.connect(DB) as conn:
        rows = conn.execute(
            "SELECT id, title_code, payload, prev_hash, record_hash FROM ledger ORDER BY id"
        ).fetchall()

        prev = "GENESIS"
        for rec_id, code, payload, prev_hash, record_hash in rows:
            if prev_hash != prev:
                return broken(rec_id, "the chain link does not match")
            if sha(prev_hash + payload) != record_hash:
                return broken(rec_id, "this record was edited")
            current = conn.execute(
                "SELECT ST_AsText(geom) FROM plots WHERE title_code = %s", (code,)
            ).fetchone()
            if current is None:
                return broken(rec_id, "the plot " + code + " was deleted")
            if current[0] != json.loads(payload)["wkt"]:
                return broken(rec_id, "the shape of " + code + " was changed")
            prev = record_hash

        not_in_ledger = conn.execute(
            """
            SELECT COUNT(*) FROM plots
            WHERE status = 'registered' AND title_code NOT IN (SELECT title_code FROM ledger)
            """
        ).fetchone()[0]

    return {"valid": True, "records": len(rows), "not_in_ledger": not_in_ledger}


# ---------- Polygon anchoring ----------
RPC = os.getenv("POLYGON_RPC", "https://polygon-amoy.drpc.org")
CHAIN_ID = 80002  # Polygon Amoy test network
EXPLORER_TX = "https://amoy.polygonscan.com/tx/"


def clean_hex(value):
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text[2:] if text.startswith("0x") else text


@app.post("/ledger/anchor", dependencies=[Depends(require_admin)])
def anchor_ledger():
    key = os.getenv("ANCHOR_PRIVATE_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="ANCHOR_PRIVATE_KEY is missing in .env")
    if not key.startswith("0x"):
        key = "0x" + key

    with psycopg.connect(DB) as conn:
        head = conn.execute("SELECT id, record_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
        if not head:
            raise HTTPException(status_code=400, detail="Nothing to anchor yet. Register a plot first.")
        ledger_id, record_hash = head

        done = conn.execute("SELECT tx_hash FROM anchors WHERE ledger_id = %s", (ledger_id,)).fetchone()
        if done:
            return {"already": True, "ledger_id": ledger_id, "tx_hash": done[0], "url": EXPLORER_TX + done[0]}

        try:
            w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
            account = w3.eth.account.from_key(key)
            # a zero-value message to ourselves, carrying the ledger fingerprint
            tx = {
                "chainId": CHAIN_ID,
                "to": account.address,
                "value": 0,
                "data": "0x" + record_hash,
                "nonce": w3.eth.get_transaction_count(account.address),
                "gas": 60000,
                "gasPrice": int(w3.eth.gas_price * 1.3),
            }
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = "0x" + clean_hex(w3.eth.send_raw_transaction(raw))
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt["status"] != 1:
                raise RuntimeError("the transaction failed on the network")
        except Exception as e:
            msg = str(e)
            if "NameResolution" in msg or "Max retries" in msg or "timed out" in msg:
                hint = "Cannot reach the Polygon network. Check your internet or try another POLYGON_RPC."
            elif "insufficient funds" in msg.lower():
                hint = "The wallet has no test POL. Get some from the faucet."
            else:
                hint = "Could not anchor on Polygon."
            raise HTTPException(status_code=502, detail=hint + " (" + msg[:100] + ")")

        conn.execute(
            "INSERT INTO anchors (ledger_id, record_hash, tx_hash, block_number) VALUES (%s, %s, %s, %s)",
            (ledger_id, record_hash, tx_hash, receipt["blockNumber"]),
        )

    return {"already": False, "ledger_id": ledger_id, "tx_hash": tx_hash, "url": EXPLORER_TX + tx_hash}


@app.get("/ledger/anchors")
def list_anchors():
    with psycopg.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT a.ledger_id, a.record_hash, a.tx_hash, a.anchored_at, l.record_hash
            FROM anchors a LEFT JOIN ledger l ON l.id = a.ledger_id
            ORDER BY a.id DESC
            """
        ).fetchall()

    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
    out = []
    for ledger_id, anchored_hash, tx_hash, at, current_hash in rows:
        on_chain = None  # None means we could not reach the network
        try:
            on_chain = clean_hex(w3.eth.get_transaction(tx_hash)["input"]) == anchored_hash
        except Exception:
            pass
        out.append(
            {
                "ledger_id": ledger_id,
                "url": EXPLORER_TX + tx_hash,
                "anchored_at": at.isoformat(),
                "matches_ledger": current_hash == anchored_hash,
                "matches_chain": on_chain,
            } 
        ) 
        
    return {"anchors": out}



# =====================================================================
# PHASE D: paste ALL of this at the very bottom of main.py.
#


# ---------- Pages ----------
@app.get("/payments")
def payments_page():
    return FileResponse("payments.html")


@app.get("/receipt")
@app.get("/receipt/{receipt_no}")
def receipt_page(receipt_no: str = ""):
    return FileResponse("receipt.html")


# ---------- Helpers ----------
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0, O, 1, I or L, so codes are easy to read out
_fails = defaultdict(deque)  # wrong tries, kept in memory (resets when the server restarts)


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


def is_admin(key):
    expected = os.getenv("ADMIN_KEY", "")
    return bool(expected and key and secrets.compare_digest(key.encode(), expected.encode()))


def normalise_code(code):
    text = re.sub(r"[^A-Z0-9]", "", code.upper())
    return text[4:] if text.startswith("SABA") else text


def code_hash(code):
    return sha(normalise_code(code))


def new_login_code():
    while True:
        chars = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        if not chars.startswith("SABA"):
            return f"SABA-{chars[:4]}-{chars[4:8]}-{chars[8:]}"


def issue_login_code(conn, payment_id, client_id, days, plots_allowed, plots_used=0):
    code = new_login_code()
    expires = conn.execute("SELECT NOW() + make_interval(days => %s)", (days,)).fetchone()[0]
    conn.execute(
        """
        INSERT INTO login_codes (payment_id, client_id, code_hash, expires_at, plots_allowed, plots_used)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (payment_id, client_id, code_hash(code), expires, plots_allowed, plots_used),
    )
    return code, expires


class PaymentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    client_type: Literal["individual", "corporate"]
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    amount_ngn: float = Field(gt=0, lt=1_000_000_000)
    method: Literal["Bank transfer", "Card or POS", "Cash", "Other"]
    reference: str = Field(min_length=3, max_length=80)
    valid_days: int = Field(default=30, ge=1, le=365)
    plots_allowed: int | None = Field(default=None, ge=1, le=1000)


class ReissueIn(BaseModel):
    valid_days: int = Field(default=30, ge=1, le=365)


class LoginIn(BaseModel):
    code: str = Field(min_length=6, max_length=40)


# ---------- Admin: record a payment and issue a login code ----------
@app.post("/api/admin/payments", dependencies=[Depends(require_admin)])
def record_payment(p: PaymentIn):
    try:
        with psycopg.connect(DB) as conn:
            client_id = conn.execute(
                "INSERT INTO clients (name, client_type, email, phone) VALUES (%s, %s, %s, %s) RETURNING id",
                (p.name.strip(), p.client_type, (p.email or "").strip() or None, (p.phone or "").strip() or None),
            ).fetchone()[0]
            n = conn.execute("SELECT nextval('receipt_seq')").fetchone()[0]
            receipt_no = f"SABA-RCPT-{datetime.now(timezone.utc).year}-{n:04d}"
            verify = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            payment_id = conn.execute(
                """
                INSERT INTO payments (client_id, receipt_no, verify_code, amount_ngn, method, reference)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (client_id, receipt_no, verify, round(p.amount_ngn, 2), p.method, p.reference.strip()),
            ).fetchone()[0]
            code, expires = issue_login_code(conn, payment_id, client_id, p.valid_days, p.plots_allowed)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="That payment reference has already been recorded.")
    return {"receipt_no": receipt_no, "verify_code": verify, "code": code, "expires_at": expires.isoformat()}


@app.get("/api/admin/payments", dependencies=[Depends(require_admin)])
def list_payments():
    with psycopg.connect(DB) as conn:
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


@app.post("/api/admin/payments/{receipt_no}/void", dependencies=[Depends(require_admin)])
def void_payment(receipt_no: str):
    with psycopg.connect(DB) as conn:
        row = conn.execute("UPDATE payments SET status = 'void' WHERE receipt_no = %s RETURNING id", (receipt_no,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Receipt not found.")
        conn.execute("UPDATE login_codes SET revoked = TRUE WHERE payment_id = %s", (row[0],))
        conn.execute(
            "DELETE FROM client_sessions WHERE code_id IN (SELECT id FROM login_codes WHERE payment_id = %s)",
            (row[0],),
        )
    return {"ok": True}


@app.post("/api/admin/payments/{receipt_no}/reissue", dependencies=[Depends(require_admin)])
def reissue_code(receipt_no: str, body: ReissueIn | None = None):
    days = body.valid_days if body else 30
    with psycopg.connect(DB) as conn:
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
    return {"code": code, "expires_at": expires.isoformat()}


# ---------- Receipts: public, but you need the verification code ----------
@app.get("/api/receipts/{receipt_no}")
def get_receipt(receipt_no: str, request: Request, v: str = "", x_admin_key: str | None = Header(default=None)):
    admin = is_admin(x_admin_key)
    if not admin:
        check_limit(request)
    with psycopg.connect(DB) as conn:
        row = conn.execute(
            """
            SELECT p.receipt_no, p.verify_code, p.amount_ngn, p.method, p.reference, p.status, p.created_at,
                   c.name, c.client_type
            FROM payments p JOIN clients c ON c.id = p.client_id
            WHERE p.receipt_no = %s
            """,
            (receipt_no.strip().upper(),),
        ).fetchone()
    good = bool(row) and (admin or secrets.compare_digest(v.strip().upper().encode(), row[1].encode()))
    if not good:
        if not admin:
            record_fail(request)
        raise HTTPException(status_code=404, detail="Receipt not found, or the verification code is wrong.")
    return {
        "receipt_no": row[0], "verify_code": row[1] if admin else None,
        "valid": row[5] == "confirmed", "status": row[5],
        "amount_ngn": float(row[2]), "method": row[3], "reference": row[4],
        "issued_at": row[6].isoformat(), "name": row[7], "client_type": row[8],
    }


# ---------- Clients: log in with a code ----------
@app.post("/api/client/login")
def client_login(body: LoginIn, request: Request):
    check_limit(request)
    with psycopg.connect(DB) as conn:
        row = conn.execute(
            """
            SELECT lc.id, lc.expires_at, lc.plots_allowed, lc.plots_used, c.name, c.client_type
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
    }


def require_client(x_client_token: str | None = Header(default=None)):
    """Used by the Register New Plot page in the next phase."""
    if not x_client_token:
        raise HTTPException(status_code=401, detail="Please log in with your login code.")
    with psycopg.connect(DB) as conn:
        row = conn.execute(
            """
            SELECT lc.id, lc.client_id, lc.plots_allowed, lc.plots_used, c.name, c.client_type, lc.expires_at
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
            "name": row[4], "client_type": row[5], "code_expires": row[6].isoformat()}


@app.get("/api/client/me")
def client_me(client=Depends(require_client)):
    return client



# =====================================================================
# PHASE E: paste ALL of this at the very bottom of main.py
# (below the Phase D code). No new imports are needed.
# =====================================================================

@app.get("/register-plot")
def register_plot_page():
    return FileResponse("register-plot.html")


@app.post("/client/register")
def client_register(plot: NewPlot, client=Depends(require_client)):
    with psycopg.connect(DB) as conn:
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
                detail="This login code has no plots left. Please ask the administrator for a new one.",
            )

        info = prepare(conn, plot)
        if find_overlaps(conn, info["wkt"], info["utm"]):
            raise HTTPException(status_code=409, detail="This plot overlaps a registered plot. Not saved.")

        code, area, wkt = conn.execute(
            """ 
            INSERT INTO plots (title_code, region_code, source, status, geom, area_m2, client_id)
            VALUES (%s, %s, 'field', 'registered', ST_GeomFromText(%s, 4326), %s, %s)
            RETURNING title_code, area_m2, ST_AsText(geom)
            """,
            (next_code(conn, plot.region, "CLT"), plot.region, info["wkt"], info["area"], client["client_id"]),
        ).fetchone()
        conn.execute("UPDATE login_codes SET plots_used = plots_used + 1 WHERE id = %s", (client["code_id"],))
        add_ledger_record(conn, code, wkt, area)

    return {"status": "REGISTERED", "title_code": code, "area_m2": round(area, 2), "region": plot.region}

 
@app.get("/api/client/plots")
def client_plots(client=Depends(require_client)):
    with psycopg.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT p.title_code, r.name, p.area_m2, p.registered_at
            FROM plots p JOIN regions r ON r.code = p.region_code
            WHERE p.client_id = %s ORDER BY p.id DESC
            """,
            (client["client_id"],),
        ).fetchall()
    return [
        {"code": r[0], "region": r[1], "area_m2": r[2],
         "registered_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ]