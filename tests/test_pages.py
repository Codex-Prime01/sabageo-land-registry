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
