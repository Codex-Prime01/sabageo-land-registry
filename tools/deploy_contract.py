"""
Deploy the TitleRegistry contract to the Polygon Amoy TEST network, once.

It uses the same test wallet as ledger anchoring (ANCHOR_PRIVATE_KEY in .env), which needs a
little test POL from the Amoy faucet. It refuses to run on any other network.
Afterwards, put the printed address in .env (and on Render) as TITLE_CONTRACT=0x...

Run it from the project folder:  python tools/deploy_contract.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web3 import Web3  # noqa: E402

from sabageo import chain, config  # noqa: E402


def main():
    key = os.getenv("ANCHOR_PRIVATE_KEY", "").strip()
    if not key:
        sys.exit("ANCHOR_PRIVATE_KEY is missing in .env")
    key = key if key.startswith("0x") else "0x" + key

    w3 = Web3(Web3.HTTPProvider(config.RPC, request_kwargs={"timeout": 30}))
    if w3.eth.chain_id != config.CHAIN_ID:
        sys.exit(f"POLYGON_RPC is chain {w3.eth.chain_id}, not Amoy ({config.CHAIN_ID}). Nothing was deployed.")
    account = w3.eth.account.from_key(key)
    balance = w3.from_wei(w3.eth.get_balance(account.address), "ether")
    print("Wallet:", account.address, "| test POL:", balance)
    if balance == 0:
        sys.exit("The wallet has no test POL. Get some from https://faucet.polygon.technology (Amoy).")

    art = chain.artifact()
    contract = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    tx = contract.constructor().build_transaction({
        "from": account.address,
        "chainId": config.CHAIN_ID,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": int(w3.eth.gas_price * 1.3),
    })
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    sent = w3.eth.send_raw_transaction(raw)
    tx_text = sent.hex() if hasattr(sent, "hex") else str(sent)
    print("Deploying… transaction", tx_text if tx_text.startswith("0x") else "0x" + tx_text)
    receipt = w3.eth.wait_for_transaction_receipt(sent, timeout=180)
    if receipt["status"] != 1:
        sys.exit("The deployment failed on the network.")
    address = receipt["contractAddress"]
    owner = w3.eth.contract(address=address, abi=art["abi"]).functions.owner().call()
    print("\nDeployed TitleRegistry at", address)
    print("Owner:", owner)
    print("See it:", "https://amoy.polygonscan.com/address/" + address)
    print("\nNow add this line to .env (and to Render's environment):")
    print("TITLE_CONTRACT=" + address)


if __name__ == "__main__":
    main()
