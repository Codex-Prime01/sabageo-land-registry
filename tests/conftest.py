"""
Shared test setup.

The tests use their OWN database, `sabageo_test`, on your local Postgres. It is built from
schema_full.sql at the start of a run and wiped before every test, so your real data is never
touched. The run stops if the database is not on this computer (so it can never hit Neon).
"""
import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # the app serves pages and static files from the project folder

import main  # noqa: E402  (loads .env, builds the app)

TEST_DB_NAME = "sabageo_test"
STAFF_PASSWORD = "test-password-123"

_real = conninfo_to_dict(main.DB)
if _real.get("host", "localhost") not in ("localhost", "127.0.0.1", "::1"):
    raise SystemExit("Tests only run against a local Postgres. Your DB settings point somewhere else.")
TEST_DB = make_conninfo(main.DB, dbname=TEST_DB_NAME)


def _point_app_at(dsn):
    """Every module that reads the DB setting at call time gets the test database."""
    main.DB = dsn
    config = sys.modules.get("sabageo.config")
    if config:
        config.DB = dsn


@pytest.fixture(scope="session", autouse=True)
def test_database():
    # create the empty test database once, if it is missing
    with psycopg.connect(make_conninfo(main.DB, dbname="postgres"), autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME)))
    # rebuild its tables from the real setup script
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute((ROOT / "schema_full.sql").read_text(encoding="utf-8"))
        for name in ("phase_h.sql", "phase_i.sql", "phase_j.sql"):  # upgrades are safe to re-run on top
            extra = ROOT / name
            if extra.exists():
                conn.execute(extra.read_text(encoding="utf-8"))
    _point_app_at(TEST_DB)
    # a light scrypt setting for tests only (each hash stores its own settings, so checks still work)
    import sabageo.security as security
    security._N = 2 ** 10
    os.environ.pop("SITE_PASSWORD", None)
    # never let a test reach a real payment provider or blockchain, whatever .env says
    for name in ("PAYSTACK_SECRET_KEY", "PAYSTACK_LIVE", "TITLE_CONTRACT", "ANCHOR_PRIVATE_KEY", "PUBLIC_URL"):
        os.environ.pop(name, None)
    yield


@pytest.fixture(autouse=True)
def clean_db(test_database):
    """Empty every data table before each test, then put the 5 NAUB pilot slots back."""
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename NOT IN ('regions', 'spatial_ref_sys')"
        ).fetchall()]
        # DELETE, not TRUNCATE: on Windows TRUNCATE remakes every table's files (about 4 s per test).
        # replica mode skips the foreign-key checks, so the order of the deletes does not matter.
        with conn.transaction():
            conn.execute("SET LOCAL session_replication_role = replica")
            for t in tables:
                conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(t)))
        for (seq,) in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'").fetchall():
            conn.execute("SELECT setval(%s, 1, false)", (seq,))  # next value is 1 again
        conn.execute(
            "INSERT INTO plots (title_code, region_code, source, status, label) "
            "SELECT 'SABA-NAUB-RES-' || LPAD(g::text, 3, '0'), 'NAUB', 'field', 'reserved', 'Pilot plot ' || g "
            "FROM generate_series(1, 5) AS g"
        )
    _clear_rate_limit()
    yield


def _clear_rate_limit():
    for mod in (main, sys.modules.get("sabageo.security")):
        for name in ("_fails", "_hits"):
            store = getattr(mod, name, None) if mod else None
            if store is not None:
                store.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture
def admin():
    """Headers of a logged-in admin. Made straight in the database (no HTTP login), to keep tests quick."""
    import secrets
    from sabageo.helpers import sha
    token = secrets.token_urlsafe(16)
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        sid = conn.execute("INSERT INTO staff (username, name, password_hash) VALUES ('boss', 'Boss', %s) RETURNING id",
                           (_hash(STAFF_PASSWORD),)).fetchone()[0]
        conn.execute("INSERT INTO staff_sessions (token_hash, staff_id, expires_at) VALUES (%s, %s, NOW() + interval '1 hour')",
                     (sha(token), sid))
    return {"X-Staff-Token": token}


def _hash(password):
    from sabageo.security import hash_password
    return hash_password(password)


def make_staff(username, password=STAFF_PASSWORD, active=True):
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("INSERT INTO staff (username, name, password_hash, active) VALUES (%s, %s, %s, %s)",
                     (username, username.title(), _hash(password), active))


def staff_login(client, username, password=STAFF_PASSWORD):
    r = client.post("/api/staff/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"X-Staff-Token": r.json()["token"]}


@pytest.fixture
def db():
    """A direct connection to the test database, for checks and setting up odd cases."""
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        yield conn


# ---------- helpers ----------
# Plots are drawn in UTM zone 31N metres near Ikeja, Lagos, so sizes are exact.
E0, N0 = 537800.0, 728650.0


def rect(e=E0, n=N0, w=18.0, h=30.0):
    """A w x h metre rectangle with its south-west corner at (e, n), as API corners."""
    pts = [(e, n), (e, n + h), (e + w, n + h), (e + w, n)]
    return [{"easting": x, "northing": y} for x, y in pts]


def body(corners, region="TST", crs="utm31"):
    return {"corners": corners, "crs": crs, "region": region}


def register(client, admin, corners, region="TST"):
    r = client.post("/register", json=body(corners, region), headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["title_code"]


def new_payment(client, admin, client_type="individual", reference="REF-001", plots_allowed=1, **extra):
    data = {
        "name": "Test Client", "client_type": client_type, "amount_ngn": 15000,
        "method": "Bank transfer", "reference": reference, "valid_days": 30,
        "plots_allowed": plots_allowed, "phone": "0803 123 4567", "email": "client@example.com",
    }
    data.update(extra)
    r = client.post("/api/admin/payments", json=data, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def login(client, code):
    r = client.post("/api/client/login", json={"code": code})
    assert r.status_code == 200, r.text
    return {"X-Client-Token": r.json()["token"]}


def owner(**extra):
    data = {"owner_type": "individual", "owner_name": "Musa Ali",
            "owner_phone": "0809 555 1212", "owner_email": "musa@example.com"}
    data.update(extra)
    return data
