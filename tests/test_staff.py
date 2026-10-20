"""Admin accounts: logging in, managing the other admins, and the rate limits."""
import os

from conftest import STAFF_PASSWORD, body, make_staff, new_payment, rect, register, staff_login


def test_login_and_me(client):
    make_staff("amina")
    h = staff_login(client, "AMINA")  # usernames are not case-sensitive
    me = client.get("/api/staff/me", headers=h).json()
    assert me["username"] == "amina" and me["name"] == "Amina"


def test_wrong_password_and_unknown_user_look_the_same(client):
    make_staff("amina")
    a = client.post("/api/staff/login", json={"username": "amina", "password": "wrong-password"})
    b = client.post("/api/staff/login", json={"username": "nobody", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_disabled_staff_cannot_log_in(client):
    make_staff("gone", active=False)
    r = client.post("/api/staff/login", json={"username": "gone", "password": STAFF_PASSWORD})
    assert r.status_code == 401


def test_old_admin_key_no_longer_works(client):
    os.environ["ADMIN_KEY"] = "old-shared-key"
    try:
        r = client.post("/register", json=body(rect()), headers={"X-Admin-Key": "old-shared-key"})
        assert r.status_code == 401
    finally:
        os.environ.pop("ADMIN_KEY", None)


def test_logout_ends_the_session(client, admin):
    assert client.post("/api/staff/logout", headers=admin).status_code == 200
    assert client.get("/api/staff/me", headers=admin).status_code == 401


# ---------- one admin level ----------
def test_any_admin_can_do_every_admin_action(client):
    make_staff("second")
    h = staff_login(client, "second")
    register(client, h, rect())
    pay = new_payment(client, h)
    assert client.post(f"/api/admin/payments/{pay['receipt_no']}/void", headers=h).status_code == 200
    assert client.get("/api/admin/overview", headers=h).status_code == 200
    assert client.get("/api/staff", headers=h).status_code == 200


def test_admin_tools_need_a_login(client):
    for method, url in (("post", "/register"), ("get", "/api/admin/payments"), ("get", "/api/admin/overview"),
                        ("post", "/ledger/anchor"), ("post", "/ledger/sync-titles"), ("get", "/api/staff")):
        assert getattr(client, method)(url).status_code == 401, url


def test_staff_log_records_who_did_what(client, admin, db):
    code = register(client, admin, rect())
    pay = new_payment(client, admin)
    rows = db.execute(
        "SELECT s.username, l.action, l.target FROM staff_log l JOIN staff s ON s.id = l.staff_id ORDER BY l.id"
    ).fetchall()
    assert ("boss", "registered plot", code) in rows
    assert ("boss", "recorded payment", pay["receipt_no"]) in rows
    recent = client.get("/api/staff", headers=admin).json()["recent"]
    assert recent[0]["action"] == "recorded payment"


def test_admin_opens_any_receipt_without_the_code(client, admin):
    pay = new_payment(client, admin)
    url = f"/api/receipts/{pay['receipt_no']}"
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url).status_code == 404


# ---------- managing the team ----------
def test_admin_adds_another_admin_who_can_then_log_in(client, admin):
    r = client.post("/api/staff", headers=admin,
                    json={"username": "New.Clerk", "name": "New Clerk", "password": "long-enough-pw"})
    assert r.status_code == 200 and r.json()["username"] == "new.clerk"
    staff_login(client, "new.clerk", "long-enough-pw")
    again = client.post("/api/staff", headers=admin,
                        json={"username": "new.clerk", "name": "Dup", "password": "long-enough-pw"})
    assert again.status_code == 409


def test_short_passwords_are_refused(client, admin):
    r = client.post("/api/staff", headers=admin,
                    json={"username": "shorty", "name": "Shorty", "password": "short"})
    assert r.status_code == 422


def test_disable_logs_them_out_at_once(client, admin):
    make_staff("leaver")
    h = staff_login(client, "leaver")
    assert client.post("/api/staff/leaver/disable", headers=admin).status_code == 200
    assert client.get("/api/staff/me", headers=h).status_code == 401
    assert client.post("/api/staff/leaver/enable", headers=admin).status_code == 200
    staff_login(client, "leaver")


def test_admin_cannot_disable_themselves(client, admin):
    assert client.post("/api/staff/boss/disable", headers=admin).status_code == 400


def test_password_reset_by_another_admin(client, admin):
    make_staff("forgot")
    h = staff_login(client, "forgot")
    r = client.post("/api/staff/forgot/password", headers=admin, json={"password": "brand-new-password"})
    assert r.status_code == 200
    assert client.get("/api/staff/me", headers=h).status_code == 401  # logged out everywhere
    assert client.post("/api/staff/login", json={"username": "forgot", "password": STAFF_PASSWORD}).status_code == 401
    staff_login(client, "forgot", "brand-new-password")


def test_change_own_password_keeps_this_device_only(client):
    make_staff("amina")
    here, other = staff_login(client, "amina"), staff_login(client, "amina")
    bad = client.post("/api/staff/me/password", headers=here, json={"current": "wrong-one", "password": "another-password"})
    assert bad.status_code == 400
    ok = client.post("/api/staff/me/password", headers=here, json={"current": STAFF_PASSWORD, "password": "another-password"})
    assert ok.status_code == 200
    assert client.get("/api/staff/me", headers=here).status_code == 200
    assert client.get("/api/staff/me", headers=other).status_code == 401


# ---------- rate limits in the database ----------
def test_too_many_wrong_passwords_locks_out(client, db):
    make_staff("amina")
    for _ in range(8):
        assert client.post("/api/staff/login", json={"username": "amina", "password": "nope-nope"}).status_code == 401
    r = client.post("/api/staff/login", json={"username": "amina", "password": STAFF_PASSWORD})
    assert r.status_code == 429  # even the right password waits now
    assert db.execute("SELECT COUNT(*) FROM rate_hits WHERE bucket = 'fail'").fetchone()[0] == 8


def test_lockout_survives_a_restart(client):
    """Wiping server memory (what a restart does) must not reset the count."""
    import sabageo.security as security
    for _ in range(8):
        client.post("/api/staff/login", json={"username": "x", "password": "nope-nope"})
    security._fails.clear()
    security._hits.clear()
    assert client.post("/api/staff/login", json={"username": "x", "password": "nope-nope"}).status_code == 429


def test_rate_limits_fall_back_to_memory_without_the_table(client, db):
    db.execute("ALTER TABLE rate_hits RENAME TO rate_hits_off")
    try:
        for _ in range(8):
            client.post("/api/staff/login", json={"username": "x", "password": "nope-nope"})
        assert client.post("/api/staff/login", json={"username": "x", "password": "nope-nope"}).status_code == 429
    finally:
        db.execute("ALTER TABLE rate_hits_off RENAME TO rate_hits")
