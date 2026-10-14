"""Plot shapes: turning corners into a polygon, finding overlaps, and title codes."""
import json

import psycopg
from fastapi import HTTPException

from sabageo import config
from sabageo.models import NewPlot


def prepare(conn, plot: NewPlot):
    """Turn the typed corners into a WGS84 polygon and check it makes sense."""
    if len(plot.corners) < 3:
        raise HTTPException(status_code=400, detail="A plot needs at least 3 corners")
    srid = config.CRS_CHOICES.get(plot.crs)
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
    west, south, east, north = config.NIGERIA
    if not (west <= lon <= east and south <= lat <= north):
        raise HTTPException(
            status_code=400,
            detail="These coordinates land outside Nigeria. Check the coordinate type (lat/long, or the UTM zone).",
        )
    return {"wkt": wkt, "shape": json.loads(geojson), "area": area, "utm": utm_zone(lon)}


def utm_zone(lon):
    """EPSG code of the local UTM zone, used to measure in metres."""
    return 32600 + int((lon + 180) // 6) + 1


def find_overlaps(conn, wkt, utm):
    """
    Registered plots that share real area with this shape. Touching edges do not count,
    and neither do slivers thinner than OVERLAP_TOLERANCE_M along a shared boundary.
    For each one it also returns WHERE the overlap is: the overlap zone itself, its centre,
    and how much of the registered plot it covers. Biggest overlap first.
    """
    rows = conn.execute(
        """
        WITH n AS (SELECT ST_Transform(ST_GeomFromText(%(wkt)s, 4326), %(utm)s::int) AS g),
        hits AS (
            SELECT p.title_code, p.label, r.name AS region,
                   ST_Area(ST_Transform(p.geom, %(utm)s::int)) AS plot_area,
                   ST_CollectionExtract(ST_Intersection(ST_Transform(p.geom, %(utm)s::int), n.g), 3) AS z
            FROM plots p JOIN regions r ON r.code = p.region_code, n
            WHERE p.geom IS NOT NULL
              AND ST_Intersects(p.geom, ST_GeomFromText(%(wkt)s, 4326))
        )
        SELECT title_code, label, region, ST_Area(z), plot_area,
               ST_AsGeoJSON(ST_Transform(z, 4326), 7),
               ST_Y(ST_Transform(ST_PointOnSurface(z), 4326)),
               ST_X(ST_Transform(ST_PointOnSurface(z), 4326))
        FROM hits
        WHERE NOT ST_IsEmpty(z) AND ST_Area(z) > 0.01
          AND NOT ST_IsEmpty(ST_Buffer(z, -%(half)s))   -- thinner than the tolerance: not an overlap
        ORDER BY ST_Area(z) DESC
        """,
        {"wkt": wkt, "utm": utm, "half": config.OVERLAP_TOLERANCE_M / 2},
    ).fetchall()
    return [
        {
            "title_code": r[0],
            "label": r[1],
            "region": r[2],
            "overlap_m2": round(r[3], 2),
            "share_of_plot_pct": round(100 * r[3] / r[4], 1) if r[4] else None,
            "centre": [round(r[6], 6), round(r[7], 6)],  # latitude, longitude
            "zone": json.loads(r[5]),
        }
        for r in rows
    ]


def next_code(conn, region, kind):
    n = conn.execute(
        r"""
        SELECT COALESCE(MAX(((regexp_match(title_code, '(\d+)$'))[1])::int), 0) + 1
        FROM plots WHERE region_code = %s AND title_code LIKE %s
        """,
        (region, f"SABA-{region}-{kind}-%"),
    ).fetchone()[0]
    return f"SABA-{region}-{kind}-{n:03d}"
