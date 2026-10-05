import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()
rpc = os.getenv("POLYGON_RPC", "https://rpc-amoy.polygon.technology")
print("Using:", rpc)

w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
try:
    print("Chain ID:", w3.eth.chain_id, "(should be 80002)")
    key = os.getenv("ANCHOR_PRIVATE_KEY")
    addr = w3.eth.account.from_key(key if key.startswith("0x") else "0x" + key).address
    print("Wallet:", addr)
    print("Balance (POL):", w3.from_wei(w3.eth.get_balance(addr), "ether"))
except Exception as e:
    print("Failed:", str(e)[:200])