"""Client accounts: sign up, log in, see my receipts, add a receipt, new code, start registering."""
from conftest import body, login, new_payment, rect
from test_paystack import callback, code_from, fake  # noqa: F401  (fake is a fixture)


def signup(client, email="ada@example.com", password="ada-password"):
    r = client.post("/api/account/signup", json={"name": "Ada Obi", "email": email, "phone": "0803 111 2222",
                                                 "password": password})
    assert r.status_code == 200, r.text
    return {"X-Account-Token": r.json()["token"]}


def claim(client, acct, pay):
    return client.post("/api/account/claim", headers=acct,
                       json={"receipt_no": pay["receipt_no"], "verify_code": pay["verify_code"]})


def test_signup_login_and_me(client):
    signup(client, email="Ada@Example.com")
    r = client.post("/api/account/login", json={"email": "ada@example.com", "password": "ada-password"})
    assert r.status_code == 200
    me = client.get("/api/account/me", headers={"X-Account-Token": r.json()["token"]}).json()
    assert me["email"] == "ada@example.com" and me["payments"] == [] and me["plots"] == []


def test_same_email_twice_is_refused(client):
    signup(client)
    r = client.post("/api/account/signup", json={"name": "Other", "email": "ada@example.com", "password": "another-pw"})
    assert r.status_code == 409


def test_wrong_password_and_unknown_email_look_the_same(client):
    signup(client)
    a = client.post("/api/account/login", json={"email": "ada@example.com", "password": "nope-nope"})
    b = client.post("/api/account/login", json={"email": "who@example.com", "password": "nope-nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_me_needs_a_login(client):
    assert client.get("/api/account/me").status_code == 401
    assert client.get("/api/account/me", headers={"X-Account-Token": "made-up"}).status_code == 401


def test_add_a_cash_receipt_with_its_verification_code(client, admin):
    acct = signup(client)
    pay = new_payment(client, admin)
    bad = client.post("/api/account/claim", headers=acct, json={"receipt_no": pay["receipt_no"], "verify_code": "WRONG123"})
    assert bad.status_code == 404
    assert claim(client, acct, pay).status_code == 200
    me = client.get("/api/account/me", headers=acct).json()
    assert [p["receipt_no"] for p in me["payments"]] == [pay["receipt_no"]]
    assert me["payments"][0]["code_state"] == "active"


def test_a_receipt_cannot_be_taken_by_a_second_account(client, admin):
    pay = new_payment(client, admin)
    assert claim(client, signup(client, "one@example.com"), pay).status_code == 200
    assert claim(client, signup(client, "two@example.com"), pay).status_code == 409


def test_start_registering_without_typing_the_code(client, admin):
    acct = signup(client)
    pay = new_payment(client, admin, client_type="corporate", plots_allowed=None)
    claim(client, acct, pay)
    r = client.post(f"/api/account/payments/{pay['receipt_no']}/start", headers=acct)
    assert r.status_code == 200
    h = {"X-Client-Token": r.json()["token"]}
    assert client.post("/client/check", json=body(rect(), region="LAG"), headers=h).status_code == 200


def test_cannot_use_someone_elses_receipt(client, admin):
    pay = new_payment(client, admin)
    claim(client, signup(client, "owner@example.com"), pay)
    thief = signup(client, "thief@example.com")
    assert client.post(f"/api/account/payments/{pay['receipt_no']}/start", headers=thief).status_code == 404
    assert client.post(f"/api/account/payments/{pay['receipt_no']}/new-code", headers=thief).status_code == 404


def test_new_code_replaces_the_old_one_and_gives_nothing_extra(client, admin, db):
    acct = signup(client)
    pay = new_payment(client, admin)  # Individual: one plot
    claim(client, acct, pay)
    old = login(client, pay["code"])
    before = db.execute("SELECT expires_at, plots_allowed FROM login_codes ORDER BY id DESC LIMIT 1").fetchone()

    r = client.post(f"/api/account/payments/{pay['receipt_no']}/new-code", headers=acct)
    assert r.status_code == 200
    new = r.json()["code"]
    assert new != pay["code"]
    assert client.post("/api/client/login", json={"code": pay["code"]}).status_code == 401  # old code is dead
    assert client.get("/api/client/me", headers=old).status_code == 401                    # and its session
    login(client, new)
    after = db.execute("SELECT expires_at, plots_allowed FROM login_codes ORDER BY id DESC LIMIT 1").fetchone()
    assert after == before  # same expiry and plot limit


def test_new_code_keeps_the_one_plot_lock(client, admin):
    acct = signup(client)
    pay = new_payment(client, admin)
    claim(client, acct, pay)
    h = login(client, pay["code"])
    assert client.post("/client/check", json=body(rect(), region="LAG"), headers=h).status_code == 200  # locks it
    new = client.post(f"/api/account/payments/{pay['receipt_no']}/new-code", headers=acct).json()["code"]
    h2 = login(client, new)
    other = client.post("/client/check", json=body(rect(e=538500), region="LAG"), headers=h2)
    assert other.status_code == 403  # a new code can't be used to check a second plot


def test_void_payment_cannot_start(client, admin):
    acct = signup(client)
    pay = new_payment(client, admin)
    claim(client, acct, pay)
    client.post(f"/api/admin/payments/{pay['receipt_no']}/void", headers=admin)
    assert client.post(f"/api/account/payments/{pay['receipt_no']}/start", headers=acct).status_code == 400


def test_paying_online_while_logged_in_puts_the_receipt_in_the_account(client, fake):  # noqa: F811
    acct = signup(client)
    r = client.post("/api/pay/start", headers=acct,
                    json={"plan": "individual", "name": "Ada Obi", "email": "ada@example.com"})
    assert r.status_code == 200
    loc = callback(client, r.json()["reference"]).headers["location"]
    assert code_from(loc)
    me = client.get("/api/account/me", headers=acct).json()
    assert len(me["payments"]) == 1 and me["payments"][0]["method"] == "Paystack"


def test_change_password(client):
    acct = signup(client)
    other = {"X-Account-Token": client.post("/api/account/login", json={"email": "ada@example.com", "password": "ada-password"}).json()["token"]}
    assert client.post("/api/account/password", headers=acct, json={"current": "wrong", "password": "new-password-1"}).status_code == 400
    assert client.post("/api/account/password", headers=acct, json={"current": "ada-password", "password": "new-password-1"}).status_code == 200
    assert client.get("/api/account/me", headers=acct).status_code == 200
    assert client.get("/api/account/me", headers=other).status_code == 401


# ---------- admin ----------
def test_admin_sees_every_account(client, admin):
    acct = signup(client)
    claim(client, acct, new_payment(client, admin))
    new_payment(client, admin, reference="REF-002")  # nobody has claimed this one
    d = client.get("/api/admin/accounts", headers=admin).json()
    assert d["accounts"][0]["email"] == "ada@example.com" and d["accounts"][0]["payments"] == 1
    assert d["unclaimed_payments"] == 1
    assert client.get("/api/admin/accounts").status_code == 401


def test_admin_disables_and_resets_an_account(client, admin):
    acct = signup(client)
    aid = client.get("/api/admin/accounts", headers=admin).json()["accounts"][0]["id"]
    assert client.post(f"/api/admin/accounts/{aid}/disable", headers=admin).status_code == 200
    assert client.get("/api/account/me", headers=acct).status_code == 401
    client.post(f"/api/admin/accounts/{aid}/enable", headers=admin)
    assert client.post(f"/api/admin/accounts/{aid}/password", headers=admin, json={"password": "reset-by-admin"}).status_code == 200
    assert client.post("/api/account/login", json={"email": "ada@example.com", "password": "reset-by-admin"}).status_code == 200


def test_account_pages_load(client):
    assert client.get("/account").status_code == 200
    assert client.get("/admin/clients").status_code == 200
