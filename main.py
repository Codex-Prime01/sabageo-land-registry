import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel

load_dotenv()

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


@app.post("/register")
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
 

@app.post("/plots/{title_code}/photo")
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