"""Smart-contract title records: push them (admin) and check one live (public)."""
import logging

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from sabageo import chain, config
from sabageo.db import connect
from sabageo.routes.ledger import chain_error, wallet_key
from sabageo.security import require_admin, throttle

router = APIRouter()
log = logging.getLogger("sabageo")
EXPLORER_ADDRESS = "https://amoy.polygonscan.com/address/"


def need_contract():
    address = chain.contract_address()
    if not address:
        raise HTTPException(status_code=503, detail="The title contract is not set up yet (TITLE_CONTRACT is missing in .env).")
    return address


@router.get("/api/chain/status")
def chain_status():
    address = chain.contract_address()
    return {"configured": bool(address), "address": address,
            "url": EXPLORER_ADDRESS + address if address else None}


@router.post("/ledger/sync-titles", dependencies=[Depends(require_admin)])
def sync_titles():
    """Write every title whose latest ledger record is not on-chain yet. Safe to press again."""
    address = need_contract()
    key = wallet_key()
    sent = []
    out_of_funds = False
    wallet = None
    with connect() as conn:
        try:
            with conn.transaction():
                remaining = chain.count_pending(conn)
        except psycopg.errors.UndefinedTable:
            raise HTTPException(status_code=503, detail="Run phase_h.sql on this database first.")
        if not remaining:
            return {"sent": 0, "batches": [], "remaining": 0, "contract": EXPLORER_ADDRESS + address}
        try:
            w3 = chain.connect_chain()
            account = w3.eth.account.from_key(key)
            wallet = account.address
            contract = chain.get_contract(w3, address)
            for _ in range(chain.MAX_BATCHES):
                # only send as many titles as the wallet can pay for, so a low balance still makes progress
                can_pay = chain.affordable(w3, account)
                if can_pay == 0:
                    out_of_funds = True
                    if not sent:
                        raise HTTPException(status_code=402, detail=(
                            "The test wallet has run out of test POL, so no titles could be written. "
                            f"Each title costs about {chain.cost_per_title_pol(w3):.4f} test POL. Get free test POL "
                            f"for wallet {wallet} at https://faucet.polygon.technology (choose Amoy), then try again."))
                    break
                rows = chain.pending_titles(conn, can_pay)
                if not rows:
                    break
                tx_hash = chain.send_batch(w3, account, contract, rows)
                # the chain has it now; if saving fails, the next sync resends and the contract skips it
                chain.save_batch(conn, rows, tx_hash)
                sent.append({"count": len(rows), "tx_hash": tx_hash, "url": config.EXPLORER_TX + tx_hash})
        except HTTPException:
            raise
        except Exception as e:
            if sent:  # some batches made it: report them instead of hiding them behind an error
                log.warning("Title sync stopped after %d batches: %s", len(sent), str(e)[:200])
            else:
                raise chain_error(e, "write the titles")
        remaining = chain.count_pending(conn)
    return {"sent": sum(b["count"] for b in sent), "batches": sent, "remaining": remaining,
            "contract": EXPLORER_ADDRESS + address, "out_of_funds": out_of_funds and remaining > 0,
            "wallet": wallet}


@router.get("/api/verify/{title_code}/chain")
def title_on_chain(title_code: str, request: Request):
    """Ask the contract itself (live) whether it holds this title's latest ledger fingerprint."""
    address = need_contract()
    throttle(request, "chain_read", limit=30, window=600)  # each call reaches the blockchain network
    code = title_code.strip().upper()
    with connect() as conn:
        rec = conn.execute(
            "SELECT id, record_hash FROM ledger WHERE title_code = %s ORDER BY id DESC LIMIT 1", (code,)
        ).fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="No title with that code.")
    try:
        w3 = chain.connect_chain(timeout=15)
        got = chain.read_title(w3, chain.get_contract(w3, address), code)
    except HTTPException:
        raise
    except Exception as e:
        raise chain_error(e, "read the title")
    on_chain = got["ledger_id"] > 0
    return {
        "title_code": code,
        "on_chain": on_chain,
        "matches_latest": on_chain and got["ledger_id"] == rec[0] and got["record_hash"] == rec[1],
        "behind": on_chain and got["ledger_id"] < rec[0],
        "removed": got["removed"],
        "ledger_id": got["ledger_id"],
        "updated_at": got["updated_at"],
        "contract": EXPLORER_ADDRESS + address,
    }
