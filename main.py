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
from PIL import Image, ImageOps
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel
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


# ---------- Pages and reading data ----------
@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/health")
def health():
    # tiny route for the keep-awake pinger; it does not touch the database
    return {"ok": True}


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
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code)
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
            },
            "geometry": json.loads(r[4]),
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


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
RPC = os.getenv("POLYGON_RPC", "https://rpc-amoy.polygon.technology")
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