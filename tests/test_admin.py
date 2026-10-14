"""Admin dashboard (Phase H2)."""
from conftest import E0, body, login, new_payment, owner, rect, register


def test_overview_needs_admin_key(client):
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers={"X-Admin-Key": "nope"}).status_code == 401


def test_admin_page_loads(client):
    assert client.get("/admin").status_code == 200


def test_overview_counts(client, admin):
    register(client, admin, rect(), region="LAG")
    pay = new_payment(client, admin, reference="DASH-1")
    token = login(client, pay["code"])
    code = client.post("/client/register", json={**body(rect(e=E0 + 100), "OTH"), **owner()}, headers=token).json()["title_code"]
    client.post("/check", json=body(rect(), "LAG"))            # red flag
    client.post("/check", json=body(rect(e=E0 + 500), "LAG"))  # clear

    d = client.get("/api/admin/overview", headers=admin).json()
    lag = next(r for r in d["regions"] if r["code"] == "LAG")
    oth = next(r for r in d["regions"] if r["code"] == "OTH")
    assert lag["field"] == 1 and oth["client"] == 1
    nau = next(r for r in d["regions"] if r["code"] == "NAUB")
    assert nau["reserved"] == 5

    cp = d["client_plots"][0]
    assert cp["title_code"] == code and cp["owner_phone"] == "0809 555 1212" and cp["paid_by"] == "Test Client"

    assert d["payments"]["confirmed"] == 1 and d["payments"]["total_ngn"] == 15000
    assert d["codes"] == {"active": 0, "used_up": 1, "expired": 0, "revoked": 0}  # 1 plot allowed, 1 used
    assert d["checks"]["total"] == 2 and d["checks"]["red_flags"] == 1
    assert len(d["checks"]["by_day"]) == 14 and d["checks"]["by_day"][-1]["checks"] == 2
    assert d["ledger"]["valid"] is True
    assert d["onchain_titles"] == 0


def test_check_still_works_without_check_log(client, db):
    """On a database where phase_h.sql has not run yet, /check must still answer."""
    db.execute("ALTER TABLE check_log RENAME TO check_log_away")
    try:
        r = client.post("/check", json=body(rect()))
        assert r.status_code == 200 and r.json()["status"] == "0 OVERLAP"
    finally:
        db.execute("ALTER TABLE check_log_away RENAME TO check_log")


def test_overview_works_without_phase_h_tables(client, admin, db):
    db.execute("ALTER TABLE check_log RENAME TO check_log_away")
    db.execute("ALTER TABLE chain_titles RENAME TO chain_titles_away")
    try:
        d = client.get("/api/admin/overview", headers=admin).json()
        assert d["checks"] is None and d["onchain_titles"] is None
    finally:
        db.execute("ALTER TABLE check_log_away RENAME TO check_log")
        db.execute("ALTER TABLE chain_titles_away RENAME TO chain_titles")
