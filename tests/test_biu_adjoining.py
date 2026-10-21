"""Oga Alabi's five adjoining Biu plots (20 Oct 2026): neighbours that only touch must give ZERO overlap."""
import re

import psycopg

import ingest_cities
from conftest import TEST_DB

WKTS = ingest_cities.EXACT_SETS[0][3]


def corners(wkt, shift_lon=0.0):
    """API corners (wgs84: easting = longitude, northing = latitude), without the repeated closing corner."""
    pts = re.findall(r"([\d.]+) ([\d.]+)", wkt)[:-1]
    return [{"easting": float(lon) + shift_lon, "northing": float(lat)} for lon, lat in pts]


def check(client, c):
    r = client.post("/check", json={"corners": c, "crs": "wgs84", "region": "BIU"})
    assert r.status_code == 200, r.text
    return r.json()


def test_each_plot_checks_clear_next_to_its_registered_neighbours(client, admin):
    for i, wkt in enumerate(WKTS, start=1):
        assert check(client, corners(wkt))["status"] == "0 OVERLAP", f"plot {i}"
        r = client.post("/register", json={"corners": corners(wkt), "crs": "wgs84", "region": "BIU"}, headers=admin)
        assert r.status_code == 200, r.text
    assert client.get("/ledger/verify").json()["valid"] is True

    # a copy of plot 3 moved about 5 m east covers plots 3 and 4: that IS an overlap
    moved = check(client, corners(WKTS[2], shift_lon=0.00005))
    assert moved["status"] == "RED FLAG" and len(moved["overlaps"]) == 2


def test_loader_adds_them_with_zero_overlap_and_a_valid_ledger(client):
    with psycopg.connect(TEST_DB) as conn:
        ingest_cities.run(conn)
    with psycopg.connect(TEST_DB) as conn:
        rows = conn.execute("""
            SELECT title_code, area_m2 FROM plots
            WHERE region_code = 'BIU' AND label LIKE 'Adjoining test plot %' ORDER BY id""").fetchall()
        shared = conn.execute("""
            SELECT COALESCE(SUM(ST_Area(ST_Intersection(a.geom, b.geom)::geography)), 0)
            FROM plots a JOIN plots b ON a.id < b.id
            WHERE a.label LIKE 'Adjoining test plot %' AND b.label LIKE 'Adjoining test plot %'""").fetchone()[0]
    assert [r[0] for r in rows] == [f"SABA-BIU-SYN-{n:03d}" for n in range(6, 11)]
    assert all(abs(r[1] - 485) < 5 for r in rows)
    assert shared == 0
    assert client.get("/ledger/verify").json()["valid"] is True
