"""Online payments through Paystack (Phase H, step 6). Paystack itself is faked: no internet."""
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import pytest

from sabageo.routes import paystack as ps

KEY = "sk_test_fake_key_for_tests"


class FakePaystack:
    """Stands in for api.paystack.co. `result` decides what /transaction/verify reports."""

    def __init__(self):
        self.calls = []
        self.result = {"status": "success", "currency": "NGN", "amount_override": None}
        self.amounts = {}

    def __call__(self, method, url, timeout=None, headers=None, json=None, **kw):
        assert headers["Authorization"] == "Bearer " + KEY
        self.calls.append((method, url))

        class R:
            ok = True
            status_code = 200

            def __init__(self, data):
                self._d = data

            def json(self):
                return self._d

        if url.endswith("/transaction/initialize"):
            self.amounts[json["reference"]] = json["amount"]
            assert json["callback_url"].endswith("/pay/callback")
            return R({"status": True, "data": {"authorization_url": "https://checkout.paystack.test/" + json["reference"]}})
        if "/transaction/verify/" in url:
            ref = url.rsplit("/", 1)[1]
            amount = self.result["amount_override"] or self.amounts.get(ref, 0)
            return R({"status": True, "data": {"status": self.result["status"], "reference": ref,
                                                "amount": amount, "currency": self.result["currency"]}})
        raise AssertionError("unexpected Paystack call " + url)


@pytest.fixture
def fake(monkeypatch):
    f = FakePaystack()
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", KEY)
    monkeypatch.setattr(ps.requests, "request", f)
    return f


def start(client, plan="individual", **extra):
    data = {"plan": plan, "name": "Ada Obi", "email": "ada@example.com", "phone": "0803 111 2222", **extra}
    r = client.post("/api/pay/start", json=data)
    assert r.status_code == 200, r.text
    return r.json()["reference"]


def callback(client, ref):
    return client.get("/pay/callback", params={"reference": ref}, follow_redirects=False)


def code_from(location):
    return parse_qs(urlparse(location).fragment)["code"][0]


# ---------- switched off ----------
def test_off_without_key(client):
    assert client.get("/api/pay/config").json() == {"enabled": False, "test_mode": False}
    r = client.post("/api/pay/start", json={"plan": "individual", "name": "Ada", "email": "a@b.co"})
    assert r.status_code == 503


def test_live_key_refused_without_flag(client, monkeypatch):
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_live_realmoney")
    monkeypatch.delenv("PAYSTACK_LIVE", raising=False)
    assert client.get("/api/pay/config").json()["enabled"] is False


def test_test_key_turns_it_on(client, fake):
    assert client.get("/api/pay/config").json() == {"enabled": True, "test_mode": True}


# ---------- the happy path ----------
def test_full_payment_gives_working_code(client, fake, db):
    ref = start(client)
    intent = db.execute("SELECT amount_kobo, status FROM pay_intents WHERE reference = %s", (ref,)).fetchone()
    assert intent == (1500000, "pending")  # 15,000 naira in kobo, from OUR price list

    r = callback(client, ref)
    assert r.status_code == 303 and r.headers["location"].startswith("/receipt/SABA-RCPT-")
    code = code_from(r.headers["location"])
    tok = client.post("/api/client/login", json={"code": code})
    assert tok.status_code == 200 and tok.json()["plots_allowed"] == 1

    pay = db.execute("SELECT method, amount_ngn, reference FROM payments").fetchall()
    assert pay == [("Paystack", 15000, ref)]


def test_corporate_plan_has_no_plot_limit(client, fake):
    code = code_from(callback(client, start(client, plan="corporate")).headers["location"])
    me = client.post("/api/client/login", json={"code": code}).json()
    assert me["plots_allowed"] is None


# ---------- repeats and races ----------
def test_second_callback_does_not_pay_twice_or_reshow_code(client, fake, db):
    ref = start(client)
    first = callback(client, ref)
    again = callback(client, ref)
    assert "#code=" in first.headers["location"]
    assert "#code=" not in again.headers["location"] and again.headers["location"].startswith("/receipt/")
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def sign(body):
    return hmac.new(KEY.encode(), body, hashlib.sha512).hexdigest()


def webhook(client, ref, signature=None, event="charge.success"):
    body = json.dumps({"event": event, "data": {"reference": ref}}).encode()
    return client.post("/api/pay/webhook", content=body,
                       headers={"x-paystack-signature": signature if signature is not None else sign(body),
                                "content-type": "application/json"})


def test_webhook_then_callback_still_shows_a_working_code(client, fake, db):
    ref = start(client)
    assert webhook(client, ref).json() == {"ok": True}
    assert db.execute("SELECT status FROM pay_intents WHERE reference = %s", (ref,)).fetchone()[0] == "paid"
    r = callback(client, ref)
    code = code_from(r.headers["location"])
    assert client.post("/api/client/login", json={"code": code}).status_code == 200
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def test_webhook_twice_records_once(client, fake, db):
    ref = start(client)
    webhook(client, ref)
    webhook(client, ref)
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


# ---------- attacks and failures ----------
def test_webhook_with_bad_signature_is_refused(client, fake, db):
    ref = start(client)
    assert webhook(client, ref, signature="0" * 128).status_code == 401
    assert webhook(client, ref, signature="").status_code == 401
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_failed_payment_is_not_recorded(client, fake, db):
    fake.result["status"] = "failed"
    r = callback(client, start(client))
    assert r.headers["location"] == "/payments?pay=failed"
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_wrong_amount_is_not_recorded(client, fake, db):
    fake.result["amount_override"] = 100  # someone paid 1 naira
    r = callback(client, start(client))
    assert r.headers["location"] == "/payments?pay=error"
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_wrong_currency_is_not_recorded(client, fake, db):
    fake.result["currency"] = "USD"
    callback(client, start(client))
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_made_up_reference_is_refused(client, fake, db):
    r = callback(client, "SABA-PS-0123456789ABCDEF")
    assert r.headers["location"] == "/payments?pay=error"
    r = callback(client, "'; DROP TABLE payments; --")
    assert r.headers["location"] == "/payments?pay=error"
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_price_comes_from_server_not_browser(client, fake, db):
    ref = start(client, amount=1)  # an extra field is ignored
    assert db.execute("SELECT amount_kobo FROM pay_intents WHERE reference = %s", (ref,)).fetchone()[0] == 1500000


def test_bad_email_is_refused(client, fake):
    r = client.post("/api/pay/start", json={"plan": "individual", "name": "Ada", "email": "not-an-email"})
    assert r.status_code == 400


def test_start_is_rate_limited(client, fake):
    for _ in range(10):
        start(client)
    r = client.post("/api/pay/start", json={"plan": "individual", "name": "Ada", "email": "ada@example.com"})
    assert r.status_code == 429
