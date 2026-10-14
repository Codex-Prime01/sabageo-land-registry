"""The tamper-evident ledger."""
import main
from conftest import N0, rect, register


def verify(client):
    return client.get("/ledger/verify").json()


def test_empty_ledger_is_valid(client):
    assert verify(client)["valid"] is True


def test_registrations_keep_chain_valid(client, admin):
    register(client, admin, rect())
    register(client, admin, rect(n=N0 + 100))
    res = verify(client)
    assert res == {"valid": True, "records": 2, "removed": 0, "not_in_ledger": 0}


def test_changed_shape_is_caught(client, admin, db):
    code = register(client, admin, rect())
    db.execute("UPDATE plots SET geom = ST_Translate(geom, 0.0001, 0) WHERE title_code = %s", (code,))
    res = verify(client)
    assert res["valid"] is False and "changed" in res["reason"]


def test_edited_record_is_caught(client, admin, db):
    register(client, admin, rect())
    db.execute("UPDATE ledger SET payload = payload || ' ' WHERE id = 1")
    res = verify(client)
    assert res["valid"] is False and "edited" in res["reason"]


def test_delete_without_record_is_caught(client, admin, db):
    code = register(client, admin, rect())
    db.execute("DELETE FROM plots WHERE title_code = %s", (code,))
    res = verify(client)
    assert res["valid"] is False and "deleted" in res["reason"]


def test_removal_record_keeps_chain_valid(client, admin, db):
    code = register(client, admin, rect())
    db.execute("DELETE FROM plots WHERE title_code = %s", (code,))
    import psycopg
    with psycopg.connect(main.DB) as conn:
        main.add_removal_record(conn, code, "test removal")
    res = verify(client)
    assert res["valid"] is True and res["removed"] == 1
