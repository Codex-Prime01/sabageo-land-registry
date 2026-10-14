"""Beacon photos: checked, shrunk, GPS-tagged and kept inside the database."""
import io
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps

from sabageo import config


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


async def read_upload(file: UploadFile):
    """Check the upload is a real JPG/PNG under the size limit. Returns the raw bytes."""
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Use a JPG or PNG photo.")
    data = await file.read()
    if len(data) > config.MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Photo is too big. Keep it under 10 MB.")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="That file is not a real image.")
    return data


def save_photo(conn, title_code, data):
    """Store a beacon photo for a plot. The caller has already checked who may do this."""
    # read the GPS tag first, because shrinking the photo removes it
    gps = read_gps(io.BytesIO(data))

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=82)
    small = out.getvalue()

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
