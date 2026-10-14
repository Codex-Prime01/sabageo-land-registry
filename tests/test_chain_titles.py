"""Smart-contract title records (Phase H, step 7). The chain is faked: no network, no gas."""
import psycopg
import pytest
from fastapi import HTTPException

import main
from conftest import N0, rect, register
from sabageo import chain

ADDRESS = "0x" + "ab" * 20


class FakeContract:
    """Follows TitleRegistry.write(): only a NEWER ledger record replaces an entry."""

    def __init__(self):
        self.titles = {}   # title_id -> (record_hash, ledger_id, removed)
        self.txs = 0

    def write(self, ids, hashes, ledger_ids, removed):
        assert len(ids) == len(hashes) == len(ledger_ids) == len(removed) <= 100
        self.txs += 1
        for i, h, lid, rm in zip(ids, hashes, ledger_ids, removed):
            assert len(i) == 32 and len(h) == 32
            if lid <= self.titles.get(bytes(i), (None, 0, False))[1]:
                continue
            self.titles[bytes(i)] = (h.hex(), lid, rm)


@pytest.fixture
def fake_chain(monkeypatch):
    c = FakeContract()
    monkeypatch.setenv("TITLE_CONTRACT", ADDRESS)
    monkeypatch.setenv("ANCHOR_PRIVATE_KEY", "0x" + "11" * 32)

    class Account:
        address = "0x" + "cd" * 20

    class Eth:
        account = type("A", (), {"from_key": staticmethod(lambda k: Account())})

    class W3:
        eth = Eth()

    monkeypatch.setattr(chain, "connect_chain", lambda timeout=30: W3())
    monkeypatch.setattr(chain, "get_contract", lambda w3, address: c)

    def send(w3, account, contract, rows):
        contract.write(*chain.batch_args(rows))
        return "0x" + f"{contract.txs:064x}"

    def read(w3, contract, code):
        h, lid, rm = contract.titles.get(bytes(chain.title_id(code)), ("00" * 32, 0, False))
        return {"record_hash": h, "ledger_id": lid, "updated_at": 1, "removed": rm}

    monkeypatch.setattr(chain, "send_batch", send)
    monkeypatch.setattr(chain, "read_title", read)
    return c


def sync(client, admin):
    r = client.post("/ledger/sync-titles", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_not_set_up_without_contract(client, admin, monkeypatch):
    monkeypatch.delenv("TITLE_CONTRACT", raising=False)
    assert client.get("/api/chain/status").json()["configured"] is False
    assert client.post("/ledger/sync-titles", headers=admin).status_code == 503


def test_sync_needs_admin(client, fake_chain):
    assert client.post("/ledger/sync-titles").status_code == 401


def test_sync_writes_every_title_once(client, admin, fake_chain, db):
    for i in range(3):
        register(client, admin, rect(n=N0 + 100 * i))
    first = sync(client, admin)
    assert first["sent"] == 3 and first["remaining"] == 0 and len(first["batches"]) == 1
    assert len(fake_chain.titles) == 3
    assert db.execute("SELECT COUNT(*) FROM chain_titles").fetchone()[0] == 3
    assert sync(client, admin)["sent"] == 0  # nothing new: no transaction at all
    assert fake_chain.txs == 1


def test_only_new_records_are_sent(client, admin, fake_chain):
    register(client, admin, rect())
    sync(client, admin)
    register(client, admin, rect(n=N0 + 100))
    assert sync(client, admin)["sent"] == 1


def test_batches_and_remaining(client, admin, fake_chain, monkeypatch):
    monkeypatch.setattr(chain, "BATCH", 2)
    monkeypatch.setattr(chain, "MAX_BATCHES", 2)
    for i in range(5):
        register(client, admin, rect(n=N0 + 100 * i))
    first = sync(client, admin)
    assert first["sent"] == 4 and first["remaining"] == 1 and len(first["batches"]) == 2
    assert sync(client, admin)["sent"] == 1


def test_removal_is_written_as_removed(client, admin, fake_chain, db):
    code = register(client, admin, rect())
    sync(client, admin)
    db.execute("DELETE FROM plots WHERE title_code = %s", (code,))
    with psycopg.connect(main.DB) as conn:
        main.add_removal_record(conn, code, "test")
    assert sync(client, admin)["sent"] == 1
    assert db.execute("SELECT action FROM chain_titles WHERE title_code = %s", (code,)).fetchone()[0] == "remove"
    assert fake_chain.titles[bytes(chain.title_id(code))][2] is True


def test_crash_after_send_is_safe_to_retry(client, admin, fake_chain, monkeypatch, db):
    """The transaction went through but saving failed: the next sync resends, the contract skips it."""
    register(client, admin, rect())
    real_save = chain.save_batch
    monkeypatch.setattr(chain, "save_batch", lambda *a: (_ for _ in ()).throw(RuntimeError("db hiccup")))
    assert client.post("/ledger/sync-titles", headers=admin).status_code == 502
    assert db.execute("SELECT COUNT(*) FROM chain_titles").fetchone()[0] == 0
    monkeypatch.setattr(chain, "save_batch", real_save)
    again = sync(client, admin)
    assert again["sent"] == 1 and again["remaining"] == 0
    assert len(fake_chain.titles) == 1  # written once, the resend was skipped
    assert db.execute("SELECT COUNT(*) FROM chain_titles").fetchone()[0] == 1


def test_live_check_and_verify_page_data(client, admin, fake_chain):
    code = register(client, admin, rect())
    before = client.get(f"/api/verify/{code}/chain").json()
    assert before["on_chain"] is False
    sync(client, admin)
    after = client.get(f"/api/verify/{code}/chain").json()
    assert after["on_chain"] and after["matches_latest"] and not after["behind"]
    assert client.get(f"/api/verify/{code}").json()["onchain"]["url"].endswith("%064x" % 1)


def test_live_check_unknown_title(client, fake_chain):
    assert client.get("/api/verify/SABA-NOPE-001/chain").status_code == 404


def test_wrong_network_is_refused(monkeypatch):
    class Eth:
        chain_id = 137  # Polygon MAINNET: must never be used

    class FakeWeb3:
        HTTPProvider = staticmethod(lambda *a, **k: None)

        def __init__(self, provider):
            self.eth = Eth()

    monkeypatch.setattr(chain, "Web3", FakeWeb3)
    with pytest.raises(HTTPException) as e:
        chain.connect_chain()
    assert "not the Polygon Amoy test network" in e.value.detail


def test_batch_args_shape():
    rows = [("SABA-TST-RES-001", 7, "ab" * 32, '{"wkt": "x"}'),
            ("SABA-TST-RES-002", 9, "cd" * 32, '{"action": "removed"}')]
    ids, hashes, lids, removed = chain.batch_args(rows)
    assert [len(i) for i in ids] == [32, 32] and hashes[0] == bytes.fromhex("ab" * 32)
    assert lids == [7, 9] and removed == [False, True]


def test_contract_artifact_is_compiled():
    art = chain.artifact()
    names = {f["name"] for f in art["abi"] if f.get("type") == "function"}
    assert {"write", "get", "owner", "titleCount"} <= names
    assert art["bytecode"].startswith("0x") and len(art["bytecode"]) > 1000
