"""Token payments, login codes, receipts and Register New Plot."""
from conftest import E0, N0, body, login, new_payment, owner, rect


def client_register(client, token, corners, region="OTH", **owner_extra):
    return client.post("/client/register", json={**body(corners, region), **owner(**owner_extra)}, headers=token)


def test_admin_routes_need_key(client):
    assert client.get("/api/admin/payments").status_code == 401
    assert client.post("/api/admin/payments", json={}).status_code in (401, 422)


def test_payment_issues_working_code(client, admin):
    pay = new_payment(client, admin)
    assert pay["code"].startswith("SABA-") and pay["receipt_no"].startswith("SABA-RCPT-")
    token = login(client, pay["code"])
    me = client.get("/api/client/me", headers=token).json()
    assert me["name"] == "Test Client" and me["plots_allowed"] == 1


def test_code_works_without_dashes_or_case(client, admin):
    code = new_payment(client, admin)["code"]
    login(client, code.replace("-", "").lower())


def test_wrong_code_is_refused(client):
    r = client.post("/api/client/login", json={"code": "SABA-AAAA-BBBB-CCCC"})
    assert r.status_code == 401


def test_duplicate_reference_is_refused(client, admin):
    new_payment(client, admin, reference="SAME-REF")
    r = client.post("/api/admin/payments", json={
        "name": "Other", "client_type": "individual", "amount_ngn": 15000,
        "method": "Cash", "reference": "same-ref"}, headers=admin)
    assert r.status_code == 409


def test_client_registers_plot_with_owner(client, admin):
    token = login(client, new_payment(client, admin)["code"])
    r = client_register(client, token, rect())
    assert r.status_code == 200, r.text
    code = r.json()["title_code"]
    assert code == "SABA-OTH-CLT-001"
    mine = client.get("/api/client/plots", headers=token).json()
    assert mine[0]["code"] == code and mine[0]["owner_name"] == "Musa Ali"
    assert client.get("/ledger/verify").json()["valid"] is True


def test_plot_limit_is_enforced(client, admin):
    token = login(client, new_payment(client, admin, plots_allowed=1)["code"])
    assert client_register(client, token, rect()).status_code == 200
    r = client_register(client, token, rect(n=N0 + 100))
    assert r.status_code == 403


def test_client_cannot_register_overlap(client, admin):
    token = login(client, new_payment(client, admin, plots_allowed=None, client_type="corporate")["code"])
    assert client_register(client, token, rect()).status_code == 200
    assert client_register(client, token, rect(e=E0 + 5)).status_code == 409


def test_client_register_needs_phone(client, admin):
    token = login(client, new_payment(client, admin)["code"])
    r = client_register(client, token, rect(), owner_phone="not a phone")
    assert r.status_code in (400, 422)


def test_client_register_refuses_pilot_and_test_regions(client, admin):
    token = login(client, new_payment(client, admin, plots_allowed=None)["code"])
    assert client_register(client, token, rect(), region="NAUB").status_code == 400
    assert client_register(client, token, rect(), region="TST").status_code == 400


def test_receipt_needs_verify_code(client, admin):
    pay = new_payment(client, admin)
    ok = client.get(f"/api/receipts/{pay['receipt_no']}", params={"v": pay["verify_code"]})
    assert ok.status_code == 200 and ok.json()["valid"] is True
    bad = client.get(f"/api/receipts/{pay['receipt_no']}", params={"v": "WRONG123"})
    assert bad.status_code == 404


def test_void_payment_blocks_login(client, admin):
    pay = new_payment(client, admin)
    assert client.post(f"/api/admin/payments/{pay['receipt_no']}/void", headers=admin).status_code == 200
    assert client.post("/api/client/login", json={"code": pay["code"]}).status_code == 401


def test_reissue_gives_new_code_and_kills_old(client, admin):
    pay = new_payment(client, admin)
    new = client.post(f"/api/admin/payments/{pay['receipt_no']}/reissue", json={"valid_days": 10}, headers=admin)
    assert new.status_code == 200
    assert client.post("/api/client/login", json={"code": pay["code"]}).status_code == 401
    login(client, new.json()["code"])
