import pytest

PAGES = ["/", "/about", "/how-it-works", "/architecture", "/registry", "/report",
         "/payments", "/receipt", "/register-plot"]


@pytest.mark.parametrize("path", PAGES)
def test_page_loads(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_static_files(client):
    for path in ("/static/app.js", "/static/site.js", "/static/site.css", "/static/style.css"):
        assert client.get(path).status_code == 200, path


def test_prices(client):
    plans = client.get("/api/prices").json()["plans"]
    assert plans["individual"]["amount"] == 15000
    assert plans["corporate"]["amount"] == 200000


def test_no_duplicate_ids_on_any_page():
    """Two elements with the same id break the page scripts (getElementById finds only the first)."""
    import re
    from collections import Counter
    from pathlib import Path
    for page in Path(".").glob("*.html"):
        if page.name.startswith("index.before"):
            continue
        ids = re.findall(r'\sid="([^"]+)"', page.read_text(encoding="utf-8"))
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        assert not dupes, f"{page.name} has duplicate ids: {dupes}"


def test_checkout_pages(client):
    for plan in ("individual", "corporate"):
        r = client.get(f"/pay/{plan}")
        assert r.status_code == 200 and "Your details" in r.text
    assert client.get("/pay/platinum").status_code == 404  # not a real plan


def test_checkout_does_not_swallow_paystack_callback(client):
    """/pay/callback must reach the payment code, not the checkout page."""
    r = client.get("/pay/callback", params={"reference": "SABA-PS-0123456789ABCDEF"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/payments?pay=")


def test_public_plans_page_has_no_staff_tools(client):
    html = client.get("/payments").text
    for staff_only in ('id="payForm"', 'id="lockForm"', "Record payment", 'id="rows"'):
        assert staff_only not in html, staff_only
    assert 'href="/pay/individual"' in html and 'href="/pay/corporate"' in html
    assert 'href="/register-plot"' in html  # "Already have a login code?"


def test_staff_payments_page_keeps_its_tools(client):
    html = client.get("/admin/payments").text
    for needed in ('id="payForm"', 'id="lockForm"', 'id="rows"', 'id="t_btn"', 'id="issued"'):
        assert needed in html, needed
