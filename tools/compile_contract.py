"""
Compile contracts/TitleRegistry.sol into contracts/TitleRegistry.json (ABI + bytecode).

Only needed when the contract changes. The server reads the JSON, so it never needs a compiler.
Needs the dev tools:  pip install -r requirements-dev.txt
Run it with:          python tools/compile_contract.py
"""
import json
from pathlib import Path

import solcx

VERSION = "0.8.24"
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "contracts" / "TitleRegistry.sol"
OUT = ROOT / "contracts" / "TitleRegistry.json"


def main():
    solcx.install_solc(VERSION)
    compiled = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": {"TitleRegistry.sol": {"content": SOURCE.read_text(encoding="utf-8")}},
            "settings": {
                "optimizer": {"enabled": True, "runs": 200},
                "evmVersion": "paris",  # widely supported; avoids opcodes some test networks lack
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=VERSION,
    )
    for err in compiled.get("errors", []):
        print(err["severity"].upper() + ":", err["formattedMessage"])
    contract = compiled["contracts"]["TitleRegistry.sol"]["TitleRegistry"]
    OUT.write_text(json.dumps({
        "compiler": "solc " + VERSION,
        "abi": contract["abi"],
        "bytecode": "0x" + contract["evm"]["bytecode"]["object"],
    }, indent=2) + "\n", encoding="utf-8")
    print("Wrote", OUT.relative_to(ROOT), "-", len(contract["evm"]["bytecode"]["object"]) // 2, "bytes of bytecode")


if __name__ == "__main__":
    main()
