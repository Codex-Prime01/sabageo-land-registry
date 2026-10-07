"""
Loads the S-VCG city dataset into the database as SYNTHETIC plots.

The dataset gives ONE point per plot, so each point becomes a small square
centred on it. Change PLOT_SIZE_M if your senior wants a different size.

Safe to run twice: plots that are already loaded are skipped.
Run it with:  python ingest_cities.py
"""
import psycopg

import main  # reuses the database settings and the ledger code

PLOT_SIZE_M = 30  # each point becomes a 30 m x 30 m square

# (label, latitude, longitude), exactly as written in the senior's document
DATASET = {
    "LAG": [  # Ikeja, Lagos State
        ("Plot 1 (Hub)", 6.5920, 3.3420),
        ("Plot 2", 6.5935, 3.3410),
        ("Plot 3", 6.5910, 3.3440),
        ("Plot 4", 6.5905, 3.3405),
        ("Plot 5", 6.5940, 3.3435),
    ],
    "ABJ": [  # Abuja, FCT
        ("Plot 1 (Hub)", 9.0765, 7.3985),
        ("Plot 2", 9.0780, 7.3960),
        ("Plot 3", 9.0750, 7.4010),
        ("Plot 4", 9.0735, 7.3970),
        ("Plot 5", 9.0795, 7.4000),
    ],
    "GMB": [  # Gombe
        ("Plot 1 (Hub)", 10.2840, 11.1670),
        ("Plot 2", 10.2860, 11.1650),
        ("Plot 3", 10.2820, 11.1690),
        ("Plot 4", 10.2815, 11.1645),
        ("Plot 5", 10.2870, 11.1685),
    ],
    "KAN": [  # Kano
        ("Plot 1 (Hub)", 11.9960, 8.5160),
        ("Plot 2", 11.9980, 8.5140),
        ("Plot 3", 11.9940, 8.5180),
        ("Plot 4", 11.9930, 8.5135),
        ("Plot 5", 11.9995, 8.5175),
    ],
    "MDG": [  # Maiduguri (plots 1, 3 and 5 of the document's last table)
        ("Plot 1 (Hub - Maiduguri)", 11.8310, 13.1510),
        ("Plot 3", 11.8330, 13.1530),
        ("Plot 5", 11.8290, 13.1480),
    ],
    "BIU": [  # Biu Emirate (plots 2 and 4 of the document's last table)
        ("Plot 2 (Hub - Biu Emirate)", 10.6120, 12.1950),
        ("Plot 4", 10.6100, 12.1920),
    ],
}


def main_run():
    added = skipped = 0
    with psycopg.connect(main.DB) as conn:
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")
        for region, points in DATASET.items():
            for label, lat, lon in points:
                if conn.execute(
                    "SELECT 1 FROM plots WHERE region_code = %s AND label = %s", (region, label)
                ).fetchone():
                    skipped += 1
                    continue

                utm = 32600 + int((lon + 180) // 6) + 1  # the local UTM zone for this point
                half = PLOT_SIZE_M / 2
                # build the square in metres, then convert it back to WGS84
                wkt = conn.execute(
                    """
                    SELECT ST_AsText(ST_Transform(
                             ST_MakeEnvelope(ST_X(c) - %s, ST_Y(c) - %s, ST_X(c) + %s, ST_Y(c) + %s, %s::int),
                             4326))
                    FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::int) AS c) t
                    """,
                    (half, half, half, half, utm, lon, lat, utm),
                ).fetchone()[0]

                if main.find_overlaps(conn, wkt, utm):
                    print("Skipped (would overlap an existing plot):", region, label)
                    skipped += 1
                    continue

                code, area, saved_wkt = conn.execute(
                    """
                    INSERT INTO plots (title_code, region_code, source, status, label, geom, area_m2)
                    VALUES (%s, %s, 'synthetic', 'registered', %s,
                            ST_GeomFromText(%s, 4326), ST_Area(ST_GeomFromText(%s, 4326)::geography))
                    RETURNING title_code, area_m2, ST_AsText(geom)
                    """,
                    (main.next_code(conn, region, "SYN"), region, label, wkt, wkt),
                ).fetchone()
                main.add_ledger_record(conn, code, saved_wkt, area)
                print("Added", code, "-", label)
                added += 1
    print(f"Done. {added} added, {skipped} skipped.")


if __name__ == "__main__":
    main_run()