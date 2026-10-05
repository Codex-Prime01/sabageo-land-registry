# SABAGeo Land Registry

A Web-GIS tool that stops the same piece of land from being registered twice.

Enter the corner coordinates of a plot. The system checks them against every registered plot and answers one of two things:

- **RED FLAG** with the plots it overlaps and the overlap area in square metres, or
- **0 OVERLAP**, after which the plot can be registered and given a unique title code.

Built as the software side of a research project on decentralized cadastre and blockchain land verification at the Nigerian Army University Biu (NAUB). The pilot area is the NAUB staff quarters and the Biu-Gombe Road layout expansion.

> **Status: working prototype.** It runs on a test blockchain with sample data. It is not a legal land registry.

## Screenshots

_Add screenshots here: the map with a red flag, the green "0 OVERLAP" result, and the phone view._

## What it does

- **Overlap detection** using PostGIS, with a rule that ignores plots that only touch along a shared boundary
- **Automatic title codes** like `SABA-NAUB-RES-001`
- **CSV import** of plot corners (easting, northing)
- **Beacon photo upload** that reads the photo's GPS tag and reports how far from the plot it was taken
- **Tamper-evident ledger**: every registration is stored in a hash chain, and one tap checks that nothing was changed or deleted
- **Polygon anchoring**: the ledger's latest fingerprint is posted to the Polygon Amoy test network, so history can be checked against a public chain
- **Satellite and street maps**, dark and light themes, and a layout that works on phones
- **Admin key** protecting registration, photo upload and anchoring

## Built with

| Part | Tool |
|---|---|
| Database | PostgreSQL + PostGIS |
| Backend | Python, FastAPI |
| Map | Leaflet, Esri imagery, OpenStreetMap |
| Blockchain | web3.py, Polygon Amoy testnet |
| Photos | Pillow (reads GPS tags) |

## How it works

1. Corners come in as **UTM Zone 32N** coordinates (EPSG:32632), which are in metres. This ties every plot to a real position on earth, and lets the database measure areas exactly.
2. PostGIS compares the new shape with all saved shapes and measures any shared area.
3. A plot is registered only if it shares no area with another plot. The check runs again on the server at registration time.
4. Each registration adds a record to the ledger. Each record contains the SHA-256 fingerprint of the one before it.
5. The latest fingerprint can be anchored on Polygon in one transaction. Because it depends on every earlier record, one anchor covers the whole ledger.

## Run it on your computer

You need Python 3, PostgreSQL with PostGIS, and Git.

```bash
git clone https://github.com/YOUR_NAME/sabageo-land-registry.git
cd sabageo-land-registry
python -m venv venv
venv\Scripts\activate          # on Windows
pip install -r requirements.txt
```

1. Create a database called `sabageo`, then run `schema.sql` on it.
2. Copy `.env.example` to `.env` and fill in your values.
3. Start the server:

```bash
uvicorn main:app --reload
```

4. Open http://127.0.0.1:8000

### Settings (`.env`)

| Name | What it is |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Your PostgreSQL login |
| `DATABASE_URL` | Optional. A full database address, used instead of the five above when hosting online |
| `ADMIN_KEY` | Password for registering plots, uploading photos and anchoring |
| `ANCHOR_PRIVATE_KEY` | Key of a **test-only** wallet holding free Amoy test coins. Never use a wallet with real money. |
| `POLYGON_RPC` | Polygon Amoy network address, for example `https://polygon-amoy.drpc.org` |

Never commit your `.env` file.

## Limitations

- The ledger and anchoring prove a record has not changed since it was written. They do not prove the survey measurements were correct.
- Anchoring uses a **test network**. Records there are for demonstration only.
- Coordinates are fixed to UTM Zone 32N. Other zones (for example Lagos, in zone 31N) need a configuration change.
- The admin key is a single shared password. A real deployment needs proper user accounts.
- Photos are stored on the server's disk.

## Roadmap

- [x] Overlap checker and registration
- [x] CSV import and beacon photos
- [x] Hash-chained ledger
- [x] Polygon anchoring
- [ ] Test with real survey data from the NAUB staff quarters
- [ ] Proper user accounts and roles
- [ ] Online deployment with cloud photo storage
- [ ] Smart contract for title records

## Author

Built by Perey, for the SABAGeo research project at NAUB.
