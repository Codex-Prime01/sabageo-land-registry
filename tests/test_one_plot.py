"""Oga Alabi, 16 Oct: an Individual code verifies ONE plot and is valid for 3 days."""
from datetime import datetime, timedelta, timezone

from conftest import E0, N0, body, login, new_payment, owner, rect

PLOT_A = rect()                       # 18 x 30 m near Ikeja
PLOT_B = rect(e=E0 + 500)             # a different plot, 500 m away


def individual(client, admin, ref="IND-1"):
    pay = new_payment(client, admin, client_type="individual", reference=ref, plots_allowed=1, valid_days=3)
    return login(client, pay["code"])


def corporate(client, admin, ref="CORP-1"):
    pay = new_payment(client, admin, client_type="corporate", reference=ref, plots_allowed=None, amount_ngn=200000)
    return login(client, pay["code"])


def check(client, token, corners, region="OTH"):
    return client.post("/client/check", json=body(corners, region), headers=token)


def register(client, token, corners, region="OTH"):
    return client.post("/client/register", json={**body(corners, region), **owner()}, headers=token)


def test_first_check_locks_the_code_to_that_plot(client, admin):
    token = individual(client, admin)
    assert client.get("/api/client/me", headers=token).json()["locked_plot"] is False
    r = check(client, token, PLOT_A)
    assert r.status_code == 200 and r.json()["status"] == "0 OVERLAP"
    me = client.get("/api/client/me", headers=token).json()
    assert me["locked_plot"] is True and me["one_plot"] is True


def test_same_plot_can_be_checked_again(client, admin):
    token = individual(client, admin)
    assert check(client, token, PLOT_A).status_code == 200
    assert check(client, token, PLOT_A).status_code == 200


def test_small_coordinate_fix_is_still_the_same_plot(client, admin):
    token = individual(client, admin)
    check(client, token, PLOT_A)
    assert check(client, token, rect(e=E0 + 2)).status_code == 200   # every corner 2 m off: a fix


def test_a_different_plot_is_refused(client, admin):
    token = individual(client, admin)
    check(client, token, PLOT_A)
    r = check(client, token, PLOT_B)
    assert r.status_code == 403 and "one plot only" in r.json()["detail"]
    assert check(client, token, rect(e=E0 + 10)).status_code == 403   # 10 m off is another plot


def test_cannot_register_a_different_plot(client, admin):
    token = individual(client, admin)
    check(client, token, PLOT_A)
    assert register(client, token, PLOT_B).status_code == 403
    assert register(client, token, PLOT_A).status_code == 200


def test_registering_without_checking_still_locks(client, admin):
    """Skipping the check must not get around the rule."""
    token = individual(client, admin)
    assert register(client, token, PLOT_A).status_code == 200
    assert check(client, token, PLOT_B).status_code == 403
    assert check(client, token, PLOT_A).status_code == 200            # its own plot: still fine


def test_corporate_codes_are_not_locked(client, admin):
    token = corporate(client, admin)
    for i in range(3):
        assert check(client, token, rect(n=N0 + 200 * i)).status_code == 200
    assert client.get("/api/client/me", headers=token).json()["locked_plot"] is False


def test_staff_can_unlock_a_mistake(client, admin):
    pay = new_payment(client, admin, client_type="individual", reference="IND-U", plots_allowed=1)
    token = login(client, pay["code"])
    check(client, token, PLOT_A)
    assert check(client, token, PLOT_B).status_code == 403
    url = f"/api/admin/payments/{pay['receipt_no']}/unlock-plot"
    assert client.post(url).status_code == 401                         # staff only
    assert client.post(url, headers=admin).status_code == 200
    assert check(client, token, PLOT_B).status_code == 200             # now locked to B
    assert check(client, token, PLOT_A).status_code == 403


def test_client_check_needs_login_and_matches_public_check(client, admin):
    assert client.post("/client/check", json=body(PLOT_A, "OTH")).status_code == 401
    from conftest import register as admin_register
    admin_register(client, admin, PLOT_A, region="LAG")
    token = corporate(client, admin)
    mine = check(client, token, PLOT_A, region="LAG").json()
    public = client.post("/check", json=body(PLOT_A, "LAG")).json()
    assert mine["status"] == public["status"] == "RED FLAG"
    assert mine["overlaps"][0]["title_code"] == public["overlaps"][0]["title_code"]


def test_two_tabs_cannot_lock_two_plots(client, admin):
    """Two logins with the same code share one lock."""
    pay = new_payment(client, admin, client_type="individual", reference="IND-T", plots_allowed=1)
    tab1, tab2 = login(client, pay["code"]), login(client, pay["code"])
    assert check(client, tab1, PLOT_A).status_code == 200
    assert check(client, tab2, PLOT_B).status_code == 403


def test_individual_plan_is_3_days(client):
    plan = client.get("/api/prices").json()["plans"]["individual"]
    assert plan["days"] == 3 and plan["plots"] == 1


def test_works_on_a_database_without_phase_i(client, admin, db):
    """Before phase_i.sql runs (e.g. Neon), logging in and checking must still work."""
    token = individual(client, admin)
    db.execute("ALTER TABLE login_codes RENAME COLUMN bound_wkt TO bound_wkt_away")
    try:
        assert client.get("/api/client/me", headers=token).status_code == 200
        assert check(client, token, PLOT_A).status_code == 200
        assert check(client, token, PLOT_B).status_code == 200          # lock is simply off
    finally:
        db.execute("ALTER TABLE login_codes RENAME COLUMN bound_wkt_away TO bound_wkt")


def test_paystack_individual_code_lasts_3_days(client, monkeypatch, db):
    """Codes bought online use the plan: 3 days, one plot."""
    from test_paystack import KEY, FakePaystack, callback, code_from, start
    from sabageo.routes import paystack as ps
    fake = FakePaystack()
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", KEY)
    monkeypatch.setattr(ps.requests, "request", fake)
    code = code_from(callback(client, start(client)).headers["location"])
    me = client.post("/api/client/login", json={"code": code}).json()
    left = datetime.fromisoformat(me["code_expires"]) - datetime.now(timezone.utc)
    assert timedelta(days=2, hours=23) < left <= timedelta(days=3) and me["plots_allowed"] == 1
