"""The hash-chained ledger: every record holds the fingerprint of the one before it."""
import json
from datetime import datetime, timezone

from sabageo.helpers import sha


def _append_ledger(conn, code, data):
    last = conn.execute("SELECT record_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last[0] if last else "GENESIS"
    payload = json.dumps(data, sort_keys=True)
    conn.execute(
        "INSERT INTO ledger (title_code, payload, prev_hash, record_hash) VALUES (%s, %s, %s, %s)",
        (code, payload, prev_hash, sha(prev_hash + payload)),
    )


def add_ledger_record(conn, code, wkt, area):
    """A registration."""
    _append_ledger(conn, code, {
        "title_code": code,
        "wkt": wkt,
        "area_m2": round(area, 2),
        "time": datetime.now(timezone.utc).isoformat(),
    })


def add_removal_record(conn, code, reason):
    """
    A removal. The ledger is never edited or shortened: when a plot is taken out
    (for example synthetic data being replaced), a new record SAYS so, with the reason.
    """
    _append_ledger(conn, code, {
        "title_code": code,
        "action": "removed",
        "reason": reason,
        "time": datetime.now(timezone.utc).isoformat(),
    })


def verify_chain(conn):
    """
    1. Every record must link to the one before it, and must not have been edited.
    2. For each title code, its LATEST record must match the registry today:
       a registration must match the plot's shape; a removal means the plot must be gone.
    """
    def broken(record_id, reason):
        return {"valid": False, "broken_at": record_id, "reason": reason}

    rows = conn.execute(
        "SELECT id, title_code, payload, prev_hash, record_hash FROM ledger ORDER BY id"
    ).fetchall()

    prev = "GENESIS"
    latest = {}
    for rec_id, code, payload, prev_hash, record_hash in rows:
        if prev_hash != prev:
            return broken(rec_id, "the chain link does not match")
        if sha(prev_hash + payload) != record_hash:
            return broken(rec_id, "this record was edited")
        latest[code] = (rec_id, json.loads(payload))
        prev = record_hash

    shapes = dict(conn.execute(
        "SELECT title_code, ST_AsText(geom) FROM plots WHERE geom IS NOT NULL"
    ).fetchall())
    registered = {r[0] for r in conn.execute("SELECT title_code FROM plots WHERE status = 'registered'").fetchall()}

    removed = 0
    for code, (rec_id, data) in sorted(latest.items(), key=lambda kv: kv[1][0]):
        if data.get("action") == "removed":
            removed += 1
            if code in shapes:
                return broken(rec_id, code + " is marked removed in the ledger but is still in the registry")
            continue
        if code not in shapes:
            return broken(rec_id, "the plot " + code + " was deleted without a removal record")
        if shapes[code] != data["wkt"]:
            return broken(rec_id, "the shape of " + code + " was changed")

    in_ledger = {c for c, (_, d) in latest.items() if d.get("action") != "removed"}
    return {
        "valid": True,
        "records": len(rows),
        "removed": removed,
        "not_in_ledger": len(registered - in_ledger),
    }
