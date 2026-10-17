"""The name is written SABAGeo, never SABAGEO (Oga Alabi, 16 Oct)."""
import re
from pathlib import Path

PAGES = [p for p in Path(".").glob("*.html") if not p.name.startswith("index.before")]
SCRIPTS = list(Path("static").glob("*.js"))
WRONG = re.compile(r"SABAGEO|SabaGEO|SabaGeo|Sabageo|SABAgeo|SABA GEO")


def test_no_misspelt_name_anywhere_visible():
    for f in PAGES + SCRIPTS:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            assert not WRONG.search(line), f"{f}:{n}: {line.strip()[:80]}"


def test_table_headers_are_not_forced_into_capitals():
    css = Path("static/site.css").read_text(encoding="utf-8")
    th = re.search(r"(?m)^th \{[^}]*\}", css).group(0)
    assert "uppercase" not in th


def test_name_never_sits_in_an_all_caps_label_without_keep_case():
    caps = re.compile(r'<(\w+)[^>]*class="[^"]*\b(eyebrow|kicker|sx-label)\b[^"]*"[^>]*>(.*?)</\1>', re.S)
    for f in PAGES:
        for m in caps.finditer(f.read_text(encoding="utf-8")):
            inner = m.group(3)
            if "SABAGeo" in inner:
                assert "keep-case" in inner, f"{f}: {m.group(0)[:80]}"
