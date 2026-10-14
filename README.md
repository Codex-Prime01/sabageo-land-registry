# SABAGeo Land Registry

A Web-GIS tool that stops the same piece of land from being registered twice.

Enter the corner coordinates of a plot. The system checks them against every registered plot and answers one of two things:

- **RED FLAG** with the plots it overlaps and the overlap area in square metres, or
- **0 OVERLAP**, after which the plot can be registered and given a unique title code.

Built as the software side of a research project on decentralized cadastre and blockchain land verification at the Nigerian Army University Biu (NAUB). The pilot area is the NAUB staff quarters and the Biu-Gombe Road layout expansion.

> **Status: working prototype.** It runs on a test blockchain. Most plots are synthetic sample data, and the five NAUB pilot slots are reserved for real field measurements. It is not a legal land registry.

## Screenshots

_Add screenshots here: the map with a red flag, the green "0 OVERLAP" result, the registry page, and the phone view._

## What it does

- **Overlap detection** using PostGIS. Plots that only touch along a shared boundary are not counted as overlapping.
- **Many places, many coordinate systems.** Plots are stored in WGS84 and can be entered as WGS84 or UTM zones 31, 32 and 33.
- **Automatic title codes** like `SABA-NAUB-RES-001` (pilot), `SABA-<REGION>-SYN-001` (sample data) and `SABA-<REGION>-CLT-001` (clients).
- **Reserved pilot slots.** Five NAUB slots are filled in order with real survey data.
- **Beacon photo upload** that reads the photo's GPS tag and reports how far from the plot it was taken.
- **Tamper-evident ledger.** Every registration is stored in a hash chain, and one tap checks that nothing was changed or deleted.
- **Polygon anchoring.** The ledger's latest fingerprint is posted to the Polygon Amoy test network, so history can be checked against a public chain.
- **Admin key** protecting admin actions, and an optional **site password** to keep the whole site private.

### Pages

| Page              | Address          | What it is                                                       |
| ----------------- | ---------------- | ---------------------------------------------------------------- |
| Map               | `/`              | Check a plot, register it, browse plots                          |
| Registered plots  | `/registry`      | Searchable list of every plot, with coordinates and cluster type |
| Parcel report     | `/report`        | Perimeter, area and a map for one plot                           |
| Register New Plot | `/register-plot` | For individual and corporate clients (needs a login code)        |
| Token payment     | `/payments`      | Pay a token and get a login code                                 |
| Payment receipt   | `/receipt`       | Look up and verify a receipt                                     |
| About us          | `/about`         | Who we are                                                       |
| How it works      | `/how-it-works`  | Plain-English walkthrough                                        |
| Architecture      | `/architecture`  | The layers, with Built / Test / Planned labels                   |

### Client flow (Phase D and E)

1. A client pays a token on the payment page and gets a receipt number, a verify code and a login code (`SABA-XXXX-XXXX-XXXX`).
2. Only the SHA-256 hash of the login code is stored. The code itself is shown once.
3. The client logs in on the Register New Plot page, checks their plot, and registers it.
4. Wrong login codes are rate-limited (8 tries per 10 minutes). Sessions last at most 12 hours.

> Payments are **simulated** for now. A real payment gateway is planned once the amount and company are decided.

## Built with

| Part       | Tool                                            |
| ---------- | ----------------------------------------------- |
| Database   | PostgreSQL + PostGIS                            |
| Backend    | Python, FastAPI                                 |
| Map        | Leaflet, Esri imagery, OpenStreetMap            |
| Blockchain | web3.py, Polygon Amoy testnet                   |
| Photos     | Pillow (reads GPS tags), stored in the database |

## How it works

1. Corners come in as WGS84 or UTM coordinates and are stored as WGS84 (EPSG:4326).
2. For measuring, PostGIS converts to the local UTM zone, so areas are in real square metres.
3. A new shape is compared with all saved shapes. A plot is registered only if it shares more than 0.01 m² with none of them. The check runs again on the server at registration time.
4. Each registration adds a record to the ledger. Each record contains the SHA-256 fingerprint of the one before it.
5. The latest fingerprint can be anchored on Polygon in one transaction. Because it depends on every earlier record, one anchor covers the whole ledger.

## Project layout

```
main.py              the server
schema_full.sql      the whole database in one file (use this for a new database)
ingest_cities.py     loads the synthetic city data (55 plots)
static/
  app.js             the map page script
  (css, html pages)
```

`schema.sql`, `phase_d.sql` and `phase_e.sql` are the same schema in steps, for upgrading an older database.

## Run it on your computer

You need Python 3, PostgreSQL with PostGIS, and Git.

```bash
git clone https://github.com/YOUR_NAME/sabageo-land-registry.git
cd sabageo-land-registry
python -m venv venv
venv\Scripts\activate          # on Windows
pip install -r requirements.txt
```

1. Create a database called `sabageo`, then run `schema_full.sql` on it.
2. Copy `.env.example` to `.env` and fill in your values.
3. Load the sample cities (optional): `python ingest_cities.py` (it should say `55 added`).
4. Start the server:

```bash
uvicorn main:app --reload
```

5. Open http://127.0.0.1:8000

### Settings (`.env`)

| Name                                                      | What it is                                                                                     |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Your PostgreSQL login                                                                          |
| `DATABASE_URL`                                            | Optional. A full database address, used instead of the five above when hosting online          |
| `ADMIN_KEY`                                               | Password for admin actions: registering pilot plots, uploading photos, anchoring               |
| `SITE_PASSWORD`                                           | Optional. If set, the whole site asks for this password first (`/health` stays open)           |
| `ANCHOR_PRIVATE_KEY`                                      | Key of a**test-only** wallet holding free Amoy test coins. Never use a wallet with real money. |
| `POLYGON_RPC`                                             | Polygon Amoy network address, for example`https://polygon-amoy.drpc.org`                       |

Never commit your `.env` file. Keep the repository private while the project is not public.

## Hosting notes

- Render (free) runs the server. Point UptimeRobot at `/health` so it stays awake.
- Neon holds the PostGIS database. Run `schema_full.sql` on it before the first deploy.
- Delete any `pywin32` line from `requirements.txt` before pushing. It breaks the Linux build.

## Limitations

- The ledger and anchoring prove a record has not changed since it was written. They do not prove the survey measurements were correct.
- Anchoring uses a **test network**. Records there are for demonstration only.
- Synthetic city plots are sample points, not surveyed land.
- The admin key is a single shared password. A real deployment needs proper user accounts.
- Payments are simulated.
- Rate limiting is kept in memory, so it resets when the server restarts.

## Roadmap

- [x] Overlap checker and registration
- [x] CSV import and beacon photos
- [x] Hash-chained ledger
- [x] Polygon anchoring
- [x] Multi-city data and coordinate systems
- [x] Registry, report, About, How it works and Architecture pages
- [x] Client payment, login code, receipt and Register New Plot
- [ ] Test with real survey data from the NAUB staff quarters
- [ ] Beacon photo upload for clients
- [ ] Real payment gateway
- [ ] Proper user accounts and roles
- [ ] Smart contract for title records

## Author

Built by Perey, for the SABAGeo research project at NAUB.
