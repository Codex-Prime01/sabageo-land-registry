from eth_account import Account

acct = Account.create()
print("Address:", acct.address)
print("Private key:", acct.key.hex())