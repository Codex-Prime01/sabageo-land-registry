"""Minna datum support and the field kit (Phase H, step 5)."""
import pytest

from conftest import body

# an 18 x 30 m plot near Biu, in UTM zone 33N metres
BIU = [(302000, 1173000), (302000, 1173030), (302018, 1173030), (302018, 1173000)]


def corners(pts):
    return [{"easting": e, "northing": n} for e, n in pts]


def centre(client, crs, pts=BIU):
    r = client.post("/check", json=body(corners(pts), crs=crs))
    assert r.status_code == 200, r.text
    ring = r.json()["shape"]["coordinates"][0][:-1]
    return sum(p[1] for p in ring) / 4, sum(p[0] for p in ring) / 4  # lat, lon


def metres_apart(a, b):
    import math
    dlat = (a[0] - b[0]) * 110574
    dlon = (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def test_minna_utm33_lands_away_from_wgs84(client):
    """Same numbers, different datum: the plot must move, by roughly the Minna shift near Biu."""
    d = metres_apart(centre(client, "utm33"), centre(client, "minna_utm33"))
    assert 60 < d < 220, d


def test_minna_plot_keeps_its_size(client):
    r = client.post("/check", json=body(corners(BIU), crs="minna_utm33")).json()
    assert abs(r["area_m2"] - 540) < 3  # a datum shift must not change the area noticeably


@pytest.mark.parametrize("crs", ["minna", "minna_utm31", "minna_utm32", "minna_utm33",
                                 "minna_west", "minna_mid", "minna_east"])
def test_round_trip_through_every_minna_type(client, admin, crs):
    """Register in WGS84, read the corners back in a Minna type, check them in that type: same plot."""
    # register with WGS84 UTM 33N (TST region keeps codes simple)
    r = client.post("/register", json={"corners": corners(BIU), "crs": "utm33", "region": "TST"}, headers=admin)
    assert r.status_code == 200, r.text
    code = r.json()["title_code"]
    got = client.get(f"/plots/{code}/coordinates", params={"crs": crs}).json()["corners"]
    if crs == "minna":  # lat, long comes back as [lat, lon]; the API wants easting=lon, northing=lat
        back = [{"easting": c[1], "northing": c[0]} for c in got]
    else:
        back = [{"easting": c[0], "northing": c[1]} for c in got]
    res = client.post("/check", json={"corners": back, "crs": crs, "region": "TST"}).json()
    assert res["status"] == "RED FLAG"
    hit = res["overlaps"][0]
    assert hit["title_code"] == code and hit["share_of_plot_pct"] > 99


def test_minna_degrees_are_range_checked(client):
    r = client.post("/check", json=body([{"easting": 500, "northing": 10}] * 3, crs="minna"))
    assert r.status_code == 400


def test_unknown_type_is_refused(client):
    assert client.post("/check", json=body(corners(BIU), crs="minna_utm34")).status_code == 400
    assert client.get("/plots/X/coordinates", params={"crs": "nope"}).status_code == 400


def test_field_kit_page_and_template(client):
    assert client.get("/field-kit").status_code == 200
    t = client.get("/static/field-kit-template.csv")
    assert t.status_code == 200 and t.text.startswith("corner,easting,northing,latitude,longitude,datum,zone")
    assert client.get("/static/csv.js").status_code == 200
