import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File,Header, HTTPException, UploadFile
import secrets
from web3 import  Web3
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel

load_dotenv(override=True)  # override with .env values if they exist

# DATABASE_URL is used later when we put the site online. Locally we use the .env values.
DB = os.getenv("DATABASE_URL") or make_conninfo(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "sabageo"),  
    user=os.getenv("DB_USER", "postgres"), 
    password=os.getenv("DB_PASSWORD", ""),
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_PHOTO_BYTES = 10 * 1024 * 1024

app = FastAPI()
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


class Corner(BaseModel):
    easting: float
    northing: float


class NewPlot(BaseModel):
    corners: list[Corner]


def make_polygon_text(corners):
    points = [(c.easting, c.northing) for c in corners]
    if points[0] != points[-1]:
        points.append(points[0])
    text = ", ".join(f"{e} {n}" for e, n in points) 
    return f"POLYGON(({text}))"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_gps(path):
    """Return (lat, lon) from the photo's GPS tag, or None if it has none."""
    try:
        gps = Image.open(path).getexif().get_ifd(0x8825)
        if not gps:
            return None

        def to_degrees(values, ref):
            d, m, s = [float(x) for x in values]
            value = d + m / 60 + s / 3600
            return -value if ref in ("S", "W") else value

        return to_degrees(gps[2], gps[1]), to_degrees(gps[4], gps[3])
    except Exception:
        return None


@app.get("/")
def home():
    return FileResponse("index.html")


@app.get("/plots")
def get_plots():
    with psycopg.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT p.title_code,
                   ST_AsGeoJSON(ST_Transform(p.geom, 4326)),
                   (SELECT COUNT(*) FROM photos ph WHERE ph.title_code = p.title_code)
            FROM plots p
            """
        ).fetchall()
    features = [
        {
            "type": "Feature",
            "properties": {"title_code": r[0], "photo_count": r[2]},
            "geometry": json.loads(r[1]),
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@app.post("/check")
def check_overlap(plot: NewPlot):
    if len(plot.corners) < 3:
        raise HTTPException(status_code=400, detail="A plot needs at least 3 corners")

    polygon = make_polygon_text(plot.corners)

    with psycopg.connect(DB) as conn:
        row = conn.execute(
            """
            SELECT ST_IsValid(g), ST_AsGeoJSON(ST_Transform(g, 4326))
            FROM (SELECT ST_GeomFromText(%s, 32632) AS g) t
            """,
            (polygon,),
        ).fetchone()

        if not row[0]:
            raise HTTPException(
                status_code=400,
                detail="Shape is invalid. Check the order of your corners.",
            )
        shape = json.loads(row[1])

        rows = conn.execute(
            """
            SELECT p.title_code,
                   ST_Area(ST_Intersection(p.geom, n.geom)) AS overlap_m2
            FROM plots p,
                 (SELECT ST_GeomFromText(%s, 32632) AS geom) n
            WHERE ST_Intersects(p.geom, n.geom)
              AND ST_Area(ST_Intersection(p.geom, n.geom)) > 0.01
            """,
            (polygon,),
        ).fetchall()

    if rows:
        return {
            "status": "RED FLAG",
            "shape": shape,
            "overlaps": [
                {"title_code": r[0], "overlap_m2": round(r[1], 2)} for r in rows
            ],
        }
    return {"status": "0 OVERLAP", "shape": shape}


# ---------- Admin lock ----------
def require_admin(x_admin_key: str | None = Header(default=None)):
    expected = os.getenv("ADMIN_KEY", "")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Admin key needed. Open the menu and tap Admin key.")


# ---------- Polygon anchoring ----------
RPC = os.getenv("POLYGON_RPC", "https://rpc-amoy.polygon.technology")
print('Polygon RPC IN USE', RPC)
CHAIN_ID = 80002  # Polygon Amoy testnet
EXPLORER_TX = "https://amoy.polygonscan.com/tx/"


def clean_hex(value):
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text[2:] if text.startswith("0x") else text


@app.post("/register", dependencies=[Depends(require_admin)])
def register_plot(plot: NewPlot):
    if len(plot.corners) < 3:
        raise HTTPException(status_code=400, detail="A plot needs at least 3 corners")

    polygon = make_polygon_text(plot.corners)

    with psycopg.connect(DB) as conn:
        # lock the table so two people can't register overlapping plots at the same moment
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")

        valid = conn.execute(
            "SELECT ST_IsValid(ST_GeomFromText(%s, 32632))", (polygon,)
        ).fetchone()[0]
        if not valid:
            raise HTTPException(status_code=400, detail="Shape is invalid. Check the order of your corners.")

        rows = conn.execute(
            """
            SELECT p.title_code
            FROM plots p,
                 (SELECT ST_GeomFromText(%s, 32632) AS geom) n
            WHERE ST_Intersects(p.geom, n.geom)
              AND ST_Area(ST_Intersection(p.geom, n.geom)) > 0.01
            """,
            (polygon,),
        ).fetchall()
        if rows:
            raise HTTPException(status_code=409, detail="This plot overlaps a registered plot. Not saved.")

        code, area, wkt = conn.execute(
            """
            INSERT INTO plots (title_code, geom, area_m2)
            VALUES (
              'SABA-NAUB-RES-' || LPAD(nextval('plot_code_seq')::text, 3, '0'),
              ST_GeomFromText(%s, 32632),
              ST_Area(ST_GeomFromText(%s, 32632))
            )
            RETURNING title_code, area_m2, ST_AsText(geom)
            """,
            (polygon, polygon),
        ).fetchone()

        # ledger: each record includes the fingerprint of the one before it
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

    return {"status": "REGISTERED", "title_code": code, "area_m2": round(area, 2)}
 

@app.post("/plots/{title_code}/photo", dependencies=[Depends(require_admin)])
async def upload_photo(title_code: str, file: UploadFile = File(...)):
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Use a JPG or PNG photo.")
    data = await file.read() 
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Photo is too big. Keep it under 10 MB.")

    name = uuid.uuid4().hex + (".jpg" if file.content_type == "image/jpeg" else ".png")
    path = UPLOAD_DIR / name
    path.write_bytes(data)

    try:
        Image.open(path).verify()
    except Exception:
        path.unlink()
        raise HTTPException(status_code=400, detail="That file is not a real image.")

    gps = read_gps(path)

    with psycopg.connect(DB) as conn:
        exists = conn.execute("SELECT 1 FROM plots WHERE title_code = %s", (title_code,)).fetchone()
        if not exists:
            path.unlink()
            raise HTTPException(status_code=404, detail="Plot not found.")

        lat = lon = distance = None
        if gps:
            lat, lon = gps
            # how far (in metres) the photo was taken from the plot; 0 means inside it
            distance = conn.execute(
                """
                SELECT ST_Distance(
                         ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 32632), geom)
                FROM plots WHERE title_code = %s
                """,
                (lon, lat, title_code),
            ).fetchone()[0]

        conn.execute(
            "INSERT INTO photos (title_code, filename, lat, lon, distance_m) VALUES (%s, %s, %s, %s, %s)",
            (title_code, name, lat, lon, distance),
        )

    return {
        "filename": name,
        "has_gps": gps is not None,
        "distance_m": round(distance, 1) if distance is not None else None,
    }


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
            "SELECT COUNT(*) FROM plots WHERE title_code NOT IN (SELECT title_code FROM ledger)"
        ).fetchone()[0]

    return {"valid": True, "records": len(rows), "not_in_ledger": not_in_ledger}



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