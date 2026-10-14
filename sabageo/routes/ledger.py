"""Checking the ledger and anchoring its fingerprint on Polygon."""
import os

from fastapi import APIRouter, Depends, HTTPException
from web3 import Web3

from sabageo import config
from sabageo.db import connect
from sabageo.ledger import verify_chain
from sabageo.security import require_admin

router = APIRouter()


@router.get("/ledger/verify")
def verify_ledger():
    with connect() as conn:
        return verify_chain(conn)


def clean_hex(value):
    text = value.hex() if hasattr(value, "hex") else str(value)
    return text[2:] if text.startswith("0x") else text


def chain_error(e, action):
    """Turn a web3 error into a message a person can act on."""
    msg = str(e)
    if "NameResolution" in msg or "Max retries" in msg or "timed out" in msg:
        hint = "Cannot reach the Polygon network. Check your internet or try another POLYGON_RPC."
    elif "insufficient funds" in msg.lower() or "exceeds allowance" in msg.lower():
        hint = "The test wallet does not have enough test POL. Get some free at https://faucet.polygon.technology (choose Amoy)."
    else:
        hint = "Could not " + action + " on Polygon."
    return HTTPException(status_code=502, detail=hint + " (" + msg[:100] + ")")


def wallet_key():
    key = os.getenv("ANCHOR_PRIVATE_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="ANCHOR_PRIVATE_KEY is missing in .env")
    return key if key.startswith("0x") else "0x" + key


@router.post("/ledger/anchor", dependencies=[Depends(require_admin)])
def anchor_ledger():
    key = wallet_key()

    with connect() as conn:
        head = conn.execute("SELECT id, record_hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
        if not head:
            raise HTTPException(status_code=400, detail="Nothing to anchor yet. Register a plot first.")
        ledger_id, record_hash = head

        done = conn.execute("SELECT tx_hash FROM anchors WHERE ledger_id = %s", (ledger_id,)).fetchone()
        if done:
            return {"already": True, "ledger_id": ledger_id, "tx_hash": done[0], "url": config.EXPLORER_TX + done[0]}

        try:
            w3 = Web3(Web3.HTTPProvider(config.RPC, request_kwargs={"timeout": 30}))
            account = w3.eth.account.from_key(key)
            # a zero-value message to ourselves, carrying the ledger fingerprint
            tx = {
                "chainId": config.CHAIN_ID,
                "to": account.address,
                "value": 0,
                "data": "0x" + record_hash,
                "nonce": w3.eth.get_transaction_count(account.address),
                "gas": 60000,
                "gasPrice": int(w3.eth.gas_price * 1.3),
            }
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            tx_hash = "0x" + clean_hex(w3.eth.send_raw_transaction(raw))
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt["status"] != 1:
                raise RuntimeError("the transaction failed on the network")
        except Exception as e:
            raise chain_error(e, "anchor")

        conn.execute(
            "INSERT INTO anchors (ledger_id, record_hash, tx_hash, block_number) VALUES (%s, %s, %s, %s)",
            (ledger_id, record_hash, tx_hash, receipt["blockNumber"]),
        )

    return {"already": False, "ledger_id": ledger_id, "tx_hash": tx_hash, "url": config.EXPLORER_TX + tx_hash}


@router.get("/ledger/anchors")
def list_anchors():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.ledger_id, a.record_hash, a.tx_hash, a.anchored_at, l.record_hash
            FROM anchors a LEFT JOIN ledger l ON l.id = a.ledger_id
            ORDER BY a.id DESC
            """
        ).fetchall()

    w3 = Web3(Web3.HTTPProvider(config.RPC, request_kwargs={"timeout": 15}))
    out = []
    for ledger_id, anchored_hash, tx_hash, at, current_hash in rows:
        on_chain = None  # None means we could not reach the network
        try:
            on_chain = clean_hex(w3.eth.get_transaction(tx_hash)["input"]) == anchored_hash
        except Exception:
            pass
        out.append(
            {
                "ledger_id": ledger_id,
                "url": config.EXPLORER_TX + tx_hash,
                "anchored_at": at.isoformat(),
                "matches_ledger": current_hash == anchored_hash,
                "matches_chain": on_chain,
            }
        )
    return {"anchors": out}
