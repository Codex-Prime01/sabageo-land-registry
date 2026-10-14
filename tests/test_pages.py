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
