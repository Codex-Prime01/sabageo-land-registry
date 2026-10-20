"""The overlap rules the whole project depends on."""
from conftest import E0, N0, body, rect, register


def check(client, corners, region="TST"):
    r = client.post("/check", json=body(corners, region))
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_map_is_clear(client):
    assert check(client, rect())["status"] == "0 OVERLAP"


def test_same_plot_is_flagged_with_details(client, admin):
    code = register(client, admin, rect())
    res = check(client, rect())
    assert res["status"] == "RED FLAG"
    hit = res["overlaps"][0]
    assert hit["title_code"] == code
    assert abs(hit["overlap_m2"] - 540) < 1
    assert hit["share_of_plot_pct"] > 99
    assert hit["zone"]["type"] in ("Polygon", "MultiPolygon")
    assert len(hit["centre"]) == 2
    assert abs(res["total_overlap_m2"] - 540) < 1


def test_touching_edge_is_not_overlap(client, admin):
    register(client, admin, rect())
    assert check(client, rect(e=E0 + 18))["status"] == "0 OVERLAP"


def test_half_shift_is_flagged(client, admin):
    register(client, admin, rect())
    res = check(client, rect(e=E0 + 9))
    assert res["status"] == "RED FLAG"
    assert abs(res["overlaps"][0]["overlap_m2"] - 270) < 1


def test_sliver_under_tolerance_is_ignored(client, admin):
    """An 8 cm strip along a shared boundary is rounding noise, not encroachment."""
    register(client, admin, rect())
    assert check(client, rect(e=E0 + 18 - 0.08))["status"] == "0 OVERLAP"


def test_real_encroachment_is_flagged(client, admin):
    """15 cm over the boundary is a real encroachment."""
    register(client, admin, rect())
    assert check(client, rect(e=E0 + 18 - 0.15))["status"] == "RED FLAG"


def test_outside_nigeria_is_rejected(client):
    r = client.post("/check", json=body(rect(), crs="wgs84"))  # metres read as degrees: far outside
    assert r.status_code == 400


def test_too_few_corners(client):
    r = client.post("/check", json=body(rect()[:2]))
    assert r.status_code == 400


def test_register_refuses_overlap(client, admin):
    register(client, admin, rect())
    r = client.post("/register", json=body(rect(e=E0 + 5)), headers=admin)
    assert r.status_code == 409


def test_register_needs_admin_key(client):
    assert client.post("/register", json=body(rect())).status_code == 401
    assert client.post("/register", json=body(rect()), headers={"X-Staff-Token": "wrong"}).status_code == 401


def test_pilot_slots_fill_in_order(client, admin):
    first = register(client, admin, rect(), region="NAUB")
    second = register(client, admin, rect(n=N0 + 100), region="NAUB")
    assert (first, second) == ("SABA-NAUB-RES-001", "SABA-NAUB-RES-002")
