"""
Loads the localized city dataset into the database as SYNTHETIC plots.

The dataset gives ONE point per plot, so it holds no real shape or size.
The shapes below are stand-ins until real surveyed corners exist:

  DISJOINT_NODE      each plot is its own rectangle, centred on its dataset point.
  ADJOINING_CLUSTER  the five plots are built as one row that really touches along
                     shared boundaries, starting at the Plot 1 point. (The dataset
                     points are about 300 m apart, so they cannot be touching
                     plots, which is why the row is anchored at Plot 1.)

Sizes are in metres. Change them below if your senior wants other sizes.
Safe to run twice: plots that are already loaded are skipped.
Run it with:  python ingest_cities.py
"""
import psycopg

import main  # reuses the database settings and the ledger code

DISJOINT = "DISJOINT_NODE"
ADJOINING = "ADJOINING_CLUSTER"

DISJOINT_SIZES = [(18, 28), (20, 30), (24, 32), (15, 30), (22, 26)]  # (east-west, north-south)
ADJOINING_WIDTHS = [15, 18, 15, 20, 15]  # east-west width of each plot in the row
ADJOINING_DEPTH = 30  # north-south depth of every plot in the row

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


def run():
    added = skipped = 0
    with psycopg.connect(main.DB) as conn:
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")
        for region, kind, points in DATASET:
            wkts, utm = shapes(conn, kind, points)
            for i, ((lat, lon), wkt) in enumerate(zip(points, wkts), start=1):
                label = f"Plot {i}"
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


if __name__ == "__main__":
    run()