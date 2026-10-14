"""Title records on the TitleRegistry smart contract (Polygon Amoy test network)."""
import json
import os
from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import HTTPException
from web3 import Web3

from sabageo import config

CONTRACT_JSON = Path(__file__).resolve().parent.parent / "contracts" / "TitleRegistry.json"
BATCH = 20         # titles per transaction (small, so a low test-POL balance still makes progress)
MAX_BATCHES = 5    # per request, so one click never runs longer than a web request should


@lru_cache(maxsize=1)
def artifact():
    return json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))


def contract_address():
    """The deployed contract's address from TITLE_CONTRACT, or None when it is not set (or not valid)."""
    addr = os.getenv("TITLE_CONTRACT", "").strip()
    return Web3.to_checksum_address(addr) if addr and Web3.is_address(addr) else None


def title_id(code):
    return Web3.keccak(text=code)


def connect_chain(timeout=30):
    """A web3 connection that is guaranteed to be the Amoy TEST network."""
    w3 = Web3(Web3.HTTPProvider(config.RPC, request_kwargs={"timeout": timeout}))
    if w3.eth.chain_id != config.CHAIN_ID:
        # a wrong POLYGON_RPC must never make us spend real POL on another network
        raise HTTPException(status_code=500, detail="POLYGON_RPC is not the Polygon Amoy test network. Nothing was sent.")
    return w3


def get_contract(w3, address):
    return w3.eth.contract(address=address, abi=artifact()["abi"])


def pending_titles(conn, limit):
    """Titles whose latest ledger record is not on-chain yet, oldest first."""
    return conn.execute(
        """
        SELECT l.title_code, l.id, l.record_hash, l.payload
        FROM ledger l
        JOIN (SELECT title_code, MAX(id) AS id FROM ledger GROUP BY title_code) m ON m.id = l.id
        LEFT JOIN chain_titles c ON c.title_code = l.title_code
        WHERE c.ledger_id IS NULL OR c.ledger_id < l.id
        ORDER BY l.id
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


def count_pending(conn):
    return conn.execute(
        """
        SELECT COUNT(*) FROM (SELECT title_code, MAX(id) AS id FROM ledger GROUP BY title_code) m
        LEFT JOIN chain_titles c ON c.title_code = m.title_code
        WHERE c.ledger_id IS NULL OR c.ledger_id < m.id
        """
    ).fetchone()[0]


def batch_args(rows):
    """Turn ledger rows into the four arrays the contract's write() takes."""
    ids, hashes, ledger_ids, removed = [], [], [], []
    for code, ledger_id, record_hash, payload in rows:
        ids.append(title_id(code))
        hashes.append(bytes.fromhex(record_hash))
        ledger_ids.append(int(ledger_id))
        removed.append(json.loads(payload).get("action") == "removed")
    return ids, hashes, ledger_ids, removed


# Rough gas cost, measured on Amoy: each new title writes two storage slots (~55k gas),
# and every transaction has a fixed part. Kept on the generous side so we never under-budget.
GAS_PER_TITLE = 70_000
GAS_PER_TX = 60_000


def affordable(w3, account):
    """How many titles the wallet can pay for in one transaction right now (0 = not even one)."""
    price = int(w3.eth.gas_price * 1.3)  # the same price send_batch uses
    gas_we_can_buy = w3.eth.get_balance(account.address) // price
    usable = gas_we_can_buy / 1.2 - GAS_PER_TX  # send_batch adds 20% headroom to the estimate
    return max(0, min(BATCH, int(usable // GAS_PER_TITLE)))


def cost_per_title_pol(w3):
    return float(w3.from_wei(int(w3.eth.gas_price * 1.3) * GAS_PER_TITLE * 1.2, "ether"))


def send_batch(w3, account, contract, rows):
    """Send one write() transaction and wait for it. Returns the transaction hash ("0x...")."""
    tx = contract.functions.write(*batch_args(rows)).build_transaction({
        "from": account.address,
        "chainId": config.CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": int(w3.eth.gas_price * 1.3),
    })
    tx["gas"] = int(tx["gas"] * 1.2)  # headroom over the estimate
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    sent = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(sent, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError("the transaction failed on the network")
    text = sent.hex() if hasattr(sent, "hex") else str(sent)
    return text if text.startswith("0x") else "0x" + text


def save_batch(conn, rows, tx_hash):
    """Remember which ledger record of each title is now on-chain."""
    with conn.transaction():
        for code, ledger_id, record_hash, payload in rows:
            action = "remove" if json.loads(payload).get("action") == "removed" else "record"
            conn.execute(
                """
                INSERT INTO chain_titles (title_code, ledger_id, record_hash, action, tx_hash)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (title_code) DO UPDATE
                SET ledger_id = EXCLUDED.ledger_id, record_hash = EXCLUDED.record_hash,
                    action = EXCLUDED.action, tx_hash = EXCLUDED.tx_hash, recorded_at = NOW()
                WHERE chain_titles.ledger_id < EXCLUDED.ledger_id
                """,
                (code, ledger_id, record_hash, action, tx_hash),
            )


def read_title(w3, contract, code):
    record_hash, ledger_id, updated_at, removed = contract.functions.get(title_id(code)).call()
    return {"record_hash": bytes(record_hash).hex(), "ledger_id": int(ledger_id),
            "updated_at": int(updated_at), "removed": bool(removed)}


def onchain_title(conn, code):
    """The on-chain title record for this code, or None (also None before that table exists)."""
    try:
        with conn.transaction():  # a savepoint, so a missing table does not spoil the connection
            row = conn.execute(
                "SELECT record_hash, tx_hash, recorded_at FROM chain_titles WHERE title_code = %s",
                (code,),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return None
    if not row:
        return None
    return {"record_hash": row[0], "url": config.EXPLORER_TX + row[1], "recorded_at": row[2].isoformat()}
