"""
Loads the localized city dataset into the database as SYNTHETIC plots (55 plots: 11 cities x 5),
plus Oga Alabi's five adjoining Biu test plots (60 in all).

The dataset gives ONE point per plot. Each point stands for a whole plot, so the
plot shape is built around it using the standard Borno layout plot the senior gave:
18 m frontage x 30 m depth (about 60 ft x 100 ft), so every plot is 540 m2.

  DISJOINT_NODE      (Lagos, Abuja, Kano, Gombe, Maiduguri, Biu)
                     each plot is its own 18 x 30 m rectangle, centred on its dataset point.
  ADJOINING_CLUSTER  (Ibadan, Port Harcourt, Benin City, Owerri, Ilorin)
                     the five plots are built as one row of 18 x 30 m plots that really
                     touch along shared boundaries. Plot 1 is centred on its dataset point.
                     (The dataset points are about 300 m apart, so they cannot be touching
                     plots, which is why the row is anchored at Plot 1.)

The 18 m side runs east-west and the 30 m side runs north-south. Real orientation comes
with real surveyed corners.

  EXACT_SETS         plots given as exact WGS84 corners, loaded as they are (no 18 x 30 m shape).
                     Oga Alabi's five adjoining Biu plots (20 Oct 2026) test that neighbours which
                     only touch give ZERO overlap in the ledger.

Safe to run twice: plots that are already loaded are skipped.
Run it with:  python ingest_cities.py
To replace old data first, use:  python reset_dataset.py
"""
import psycopg

import main  # reuses the database settings and the ledger code

DISJOINT = "DISJOINT_NODE"
ADJOINING = "ADJOINING_CLUSTER"

FRONTAGE = 18  # metres, east-west (the senior's standard plot: 18 m x 30 m)
DEPTH = 30     # metres, north-south
DISJOINT_SIZES = [(FRONTAGE, DEPTH)] * 5        # (east-west, north-south) for plots 1 to 5
ADJOINING_WIDTHS = [FRONTAGE] * 5               # east-west width of each plot in the row
ADJOINING_DEPTH = DEPTH                         # north-south depth of every plot in the row

# (region code, cluster type, five (latitude, longitude) points exactly as in the dataset tables)
DATASET = [
    # registered earlier, now marked DISJOINT_NODE
    ("LAG", DISJOINT, [(6.5920, 3.3420), (6.5935, 3.3410), (6.5910, 3.3440), (6.5905, 3.3405), (6.5940, 3.3435)]),
    ("ABJ", DISJOINT, [(9.0765, 7.3985), (9.0780, 7.3960), (9.0750, 7.4010), (9.0735, 7.3970), (9.0795, 7.4000)]),
    ("GMB", DISJOINT, [(10.2840, 11.1670), (10.2860, 11.1650), (10.2820, 11.1690), (10.2815, 11.1645), (10.2870, 11.1685)]),
    ("KAN", DISJOINT, [(11.9960, 8.5160), (11.9980, 8.5140), (11.9940, 8.5180), (11.9930, 8.5135), (11.9995, 8.5175)]),
    # new dataset: DISJOINT_NODE
    ("MDG", DISJOINT, [(11.830300, 13.147000), (11.832300, 13.149000), (11.834300, 13.151000), (11.836300, 13.153000), (11.838300, 13.155000)]),
    ("BIU", DISJOINT, [(10.609200, 12.191600), (10.611200, 12.193600), (10.613200, 12.195600), (10.615200, 12.197600), (10.617200, 12.199600)]),
    # new dataset: ADJOINING_CLUSTER
    ("IBD", ADJOINING, [(7.374500, 3.944000), (7.376500, 3.946000), (7.378500, 3.948000), (7.380500, 3.950000), (7.382500, 3.952000)]),
    ("PHC", ADJOINING, [(4.812600, 7.046800), (4.814600, 7.048800), (4.816600, 7.050800), (4.818600, 7.052800), (4.820600, 7.054800)]),
    ("BEN", ADJOINING, [(6.332000, 5.624500), (6.334000, 5.626500), (6.336000, 5.628500), (6.338000, 5.630500), (6.340000, 5.632500)]),
    ("OWR", ADJOINING, [(5.482600, 7.030600), (5.484600, 7.032600), (5.486600, 7.034600), (5.488600, 7.036600), (5.490600, 7.038600)]),
    ("ILR", ADJOINING, [(8.476900, 4.538800), (8.478900, 4.540800), (8.480900, 4.542800), (8.482900, 4.544800), (8.484900, 4.546800)]),
]


# (region code, cluster type, label, WKT polygons in WGS84, longitude first) loaded exactly as given.
# Oga Alabi, 20 Oct 2026: five 0.0002-degree squares in a row in Biu (about 21.8 m x 22.1 m each),
# every plot sharing its whole east edge with the next one.
EXACT_SETS = [
    ("BIU", ADJOINING, "Adjoining test plot", [
        "POLYGON((12.194000 10.612000, 12.194200 10.612000, 12.194200 10.612200, 12.194000 10.612200, 12.194000 10.612000))",
        "POLYGON((12.194200 10.612000, 12.194400 10.612000, 12.194400 10.612200, 12.194200 10.612200, 12.194200 10.612000))",
        "POLYGON((12.194400 10.612000, 12.194600 10.612000, 12.194600 10.612200, 12.194400 10.612200, 12.194400 10.612000))",
        "POLYGON((12.194600 10.612000, 12.194800 10.612000, 12.194800 10.612200, 12.194600 10.612200, 12.194600 10.612000))",
        "POLYGON((12.194800 10.612000, 12.195000 10.612000, 12.195000 10.612200, 12.194800 10.612200, 12.194800 10.612000))",
    ]),
]


def utm_of(lon):
    return 32600 + int((lon + 180) // 6) + 1  # the local UTM zone


def to_utm(conn, lat, lon, utm):
    return conn.execute(
        "SELECT ST_X(c), ST_Y(c) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::int) AS c) t",
        (lon, lat, utm),
    ).fetchone()


def rect_wkt(conn, utm, xmin, ymin, xmax, ymax):
    """A rectangle built in metres, returned as WGS84 text."""
    return conn.execute(
        "SELECT ST_AsText(ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, %s::int), 4326))",
        (xmin, ymin, xmax, ymax, utm),
    ).fetchone()[0]


def shapes(conn, kind, points):
    utm = utm_of(points[0][1])
    out = []
    if kind == DISJOINT:
        for (lat, lon), (w, d) in zip(points, DISJOINT_SIZES):
            x, y = to_utm(conn, lat, lon, utm)
            out.append(rect_wkt(conn, utm, x - w / 2, y - d / 2, x + w / 2, y + d / 2))
    else:
        x0, y0 = to_utm(conn, points[0][0], points[0][1], utm)
        left = x0 - ADJOINING_WIDTHS[0] / 2
        for w in ADJOINING_WIDTHS:
            out.append(rect_wkt(conn, utm, left, y0 - ADJOINING_DEPTH / 2, left + w, y0 + ADJOINING_DEPTH / 2))
            left += w  # the next plot starts exactly where this one ends, so they share a boundary
    return out, utm


def centre(conn, wkt):
    """(latitude, longitude) of a shape's middle, for the plot's reference point."""
    lon, lat = conn.execute(
        "SELECT ST_X(c), ST_Y(c) FROM (SELECT ST_Centroid(ST_GeomFromText(%s, 4326)) AS c) t", (wkt,)
    ).fetchone()
    return round(lat, 6), round(lon, 6)


def jobs(conn):
    """Every plot to load: (region, cluster type, label, (lat, lon), WGS84 text, UTM zone)."""
    for region, kind, points in DATASET:
        wkts, utm = shapes(conn, kind, points)
        for i, (point, wkt) in enumerate(zip(points, wkts), start=1):
            yield region, kind, f"Plot {i}", point, wkt, utm
    for region, kind, name, wkts in EXACT_SETS:
        for i, wkt in enumerate(wkts, start=1):
            point = centre(conn, wkt)
            yield region, kind, f"{name} {i}", point, wkt, utm_of(point[1])


def run(conn=None):
    """Load the dataset. Pass an open connection to run it inside someone else's transaction."""
    if conn is None:
        with psycopg.connect(main.DB) as own:
            return run(own)
    added = skipped = 0
    conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")
    for region, kind, label, (lat, lon), wkt, utm in list(jobs(conn)):
        if conn.execute(
            "SELECT 1 FROM plots WHERE region_code = %s AND label = %s", (region, label)
        ).fetchone():
            skipped += 1
            continue
        if main.find_overlaps(conn, wkt, utm):
            print("Skipped (would overlap an existing plot):", region, label)
            skipped += 1
            continue
        code, area, saved_wkt = conn.execute(
            """
            INSERT INTO plots (title_code, region_code, source, status, label,
                               cluster_type, ref_lat, ref_lon, geom, area_m2)
            VALUES (%s, %s, 'synthetic', 'registered', %s, %s, %s, %s,
                    ST_GeomFromText(%s, 4326), ST_Area(ST_GeomFromText(%s, 4326)::geography))
            RETURNING title_code, area_m2, ST_AsText(geom)
            """,
            (main.next_code(conn, region, "SYN"), region, label, kind, lat, lon, wkt, wkt),
        ).fetchone()
        main.add_ledger_record(conn, code, saved_wkt, area)
        print(f"Added {code}  {kind}  {area:.0f} m2")
        added += 1
    print(f"Done. {added} added, {skipped} skipped.")
    return added, skipped


if __name__ == "__main__":
    run()
