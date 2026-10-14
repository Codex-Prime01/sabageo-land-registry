"""QR title check (Phase H1)."""
import main
import psycopg
from conftest import N0, rect, register


def test_registered_title_is_intact(client, admin):
    code = register(client, admin, rect())
    d = client.get(f"/api/verify/{code}").json()
    assert d["status"] == "registered" and d["intact"] is True
    assert d["record"]["matches_plot"] is True and d["ledger_intact"] is True


def test_code_is_case_insensitive(client, admin):
    code = register(client, admin, rect())
    assert client.get(f"/api/verify/{code.lower()}").json()["intact"] is True


def test_tampered_plot_is_not_intact(client, admin, db):
    code = register(client, admin, rect())
    db.execute("UPDATE plots SET geom = ST_Translate(geom, 0.0001, 0) WHERE title_code = %s", (code,))
    d = client.get(f"/api/verify/{code}").json()
    assert d["intact"] is False and d["record"]["matches_plot"] is False


def test_removed_title(client, admin, db):
    code = register(client, admin, rect())
    db.execute("DELETE FROM plots WHERE title_code = %s", (code,))
    with psycopg.connect(main.DB) as conn:
        main.add_removal_record(conn, code, "replaced in test")
    d = client.get(f"/api/verify/{code}").json()
    assert d["status"] == "removed" and d["intact"] is False
    assert d["record"]["removed_reason"] == "replaced in test"


def test_reserved_slot(client):
    assert client.get("/api/verify/SABA-NAUB-RES-001").json()["status"] == "reserved"


def test_unknown_title(client):
    assert client.get("/api/verify/SABA-XXX-NOPE-001").status_code == 404


def test_qr_svg(client, admin):
    code = register(client, admin, rect(n=N0 + 50))
    r = client.get(f"/plots/{code}/qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content
    assert client.get("/plots/NOPE/qr.svg").status_code == 404


def test_verify_page_loads(client):
    assert client.get("/verify").status_code == 200
    assert client.get("/verify/SABA-LAG-SYN-001").status_code == 200


def test_no_owner_contact_on_verify(client, admin):
    from conftest import body, login, new_payment, owner
    token = login(client, new_payment(client, admin)["code"])
    code = client.post("/client/register", json={**body(rect(), "OTH"), **owner()}, headers=token).json()["title_code"]
    text = client.get(f"/api/verify/{code}").text
    assert "0809 555 1212" not in text and "musa@example.com" not in text
