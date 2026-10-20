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
- **Many places, many coordinate systems.** Plots are stored in WGS84 and can be entered as WGS84 or UTM zones 31, 32 and 33, or on the older **Minna** datum (lat/long, UTM 31/32/33N, Nigeria West/Mid/East Belt).
- **Shows exactly where an overlap is**: the overlap zone is shaded on the map with its area, its share of the plot and its centre.
- **Automatic title codes** like `SABA-NAUB-RES-001` (pilot), `SABA-<REGION>-SYN-001` (sample data) and `SABA-<REGION>-CLT-001` (clients).
- **Reserved pilot slots.** Five NAUB slots are filled in order with real survey data.
- **Beacon photo upload** that reads the photo's GPS tag and reports how far from the plot it was taken.
- **Tamper-evident ledger.** Every registration is stored in a hash chain, and one tap checks that nothing was changed or deleted.
- **Polygon anchoring.** The ledger's latest fingerprint is posted to the Polygon Amoy test network, so history can be checked against a public chain.
- **Title records on a smart contract.** Each title's latest ledger fingerprint can be written to the `TitleRegistry` contract on Polygon Amoy, and checked live.
- **QR "verify this title".** Every parcel report carries a QR code. Scanning it opens a public page that says whether the title is registered and its record untouched.
- **Admin dashboard** with client plots and contacts, payments, login codes, overlap checks per day and ledger health.
- **Online token payment** through Paystack, in test mode.
- **Field data kit**: a CSV template and a printable field sheet for survey teams.
- **Admin accounts** (one level, each admin has their own login) with a log of who did what, and an optional **site password** to keep the whole site private.
- **Client accounts** (My account): receipts, plots, "Register a plot" without typing a code, and a fresh login code any time.
- **Guided tour** on the map for first-time visitors (asks first, moves only when you tap Next), and an iPhone-style look: grouped lists, a phone tab bar, glass only on controls.

### Pages

| Page              | Address          | What it is                                                       |
| ----------------- | ---------------- | ---------------------------------------------------------------- |
| Map               | `/`              | Check a plot, register it, browse plots                          |
| Registered plots  | `/registry`      | Searchable list of every plot, with coordinates and cluster type |
| Parcel report     | `/report`        | Perimeter, area and a map for one plot                           |
| Register New Plot | `/register-plot` | For individual and corporate clients (needs a login code)        |
| Token payment     | `/payments`      | Pay a token and get a login code                                 |
| Payment receipt   | `/receipt`       | Look up and verify a receipt                                     |
| Verify a title    | `/verify`        | Public check of a title code (the QR code on reports opens this) |
| Field kit         | `/field-kit`     | Datum guide, CSV template and printable field sheet              |
| Admin dashboard   | `/admin`         | Client plots, payments, checks, ledger (admins only)             |
| About us          | `/about`         | Who we are                                                       |
| How it works      | `/how-it-works`  | Plain-English walkthrough                                        |
| Architecture      | `/architecture`  | The layers, with Built / Test / Planned labels                   |

### Client flow (Phase D and E)

1. A client pays a token (recorded by SABAGeo staff, or online with Paystack) and gets a receipt number, a verify code and a login code (`SABA-XXXX-XXXX-XXXX`).
2. Only the SHA-256 hash of the login code is stored. The code itself is shown once.
3. The client logs in on the Register New Plot page, checks their plot, and registers it.
4. Wrong login codes are rate-limited (8 tries per 10 minutes). Sessions last at most 12 hours.
5. An **Individual** code is for **one plot** and is valid for **3 days**: the first plot it checks is the one it is for. Corporate codes cover many plots for 30 days.
6. The client can add up to 5 beacon photos to each of their own plots.

> Online payment runs in Paystack **test mode** (no real money). The prices are provisional until the review committee approves them. A live key is refused unless `PAYSTACK_LIVE=1` is set on purpose.

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
main.py              builds the app from the sabageo/ package (start it with uvicorn main:app)
sabageo/             the server: config, db, security, geo, ledger, photos, codes, chain
  routes/            one file per area: pages, plots, ledger, chain, payments, paystack,
                     clients, verify, admin
contracts/           TitleRegistry.sol and its compiled ABI + bytecode
tools/               compile_contract.py, deploy_contract.py
tests/               automatic tests (they use their own sabageo_test database)
schema_full.sql      the whole database in one file (use this for a new database)
add_payments.sql, phase_g.sql … phase_j.sql   upgrades for an older database (safe to re-run)
ingest_cities.py     loads the synthetic city data (55 plots)
reset_dataset.py     replaces the synthetic data safely (dry run unless --go)
*.html               the pages; static/ holds app.js, site.js, csv.js and the CSS
```

## Run it on your computer

You need Python 3, PostgreSQL with PostGIS, and Git.

```bash
git clone https://github.com/YOUR_NAME/sabageo-land-registry.git
cd sabageo-land-registry
python -m venv venv
venv\Scripts\activate          # on Windows
pip install -r requirements.txt
```

1. Create a database called `sabageo`, then run `schema_full.sql` on it. (An older database: run `add_payments.sql`, `phase_g.sql`, `phase_h.sql`, `phase_i.sql` and `phase_j.sql`, in that order.)
2. Copy `.env.example` to `.env` and fill in your values.
3. Make the first admin account: `python tools/create_staff.py`. The same tool resets a forgotten password. Other admins are added on the `/staff` page.
4. Load the sample cities (optional): `python ingest_cities.py` (it should say `55 added`).
5. Start the server:

```bash
uvicorn main:app --reload
```

5. Open http://127.0.0.1:8000

### Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests build their own `sabageo_test` database on your local PostgreSQL and never touch your real data, Paystack or the blockchain.

### Smart contract (optional)

1. The anchor wallet needs some free test POL from the Amoy faucet.
2. `python tools/deploy_contract.py` deploys `TitleRegistry` and prints its address.
3. Put that address in `.env` as `TITLE_CONTRACT=0x...`, restart the server, then use **Write titles to contract** in the map menu (admin login needed). It is safe to press again.

Only re-compile (`python tools/compile_contract.py`) if you change `TitleRegistry.sol`.

### Settings (`.env`)

| Name                                                      | What it is                                                                                     |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Your PostgreSQL login                                                                          |
| `DATABASE_URL`                                            | Optional. A full database address, used instead of the five above when hosting online          |
| `SITE_PASSWORD`                                           | Optional. If set, the whole site asks for this password first (`/health` stays open)           |
| `ANCHOR_PRIVATE_KEY`                                      | Key of a**test-only** wallet holding free Amoy test coins. Never use a wallet with real money. |
| `POLYGON_RPC`                                             | Polygon Amoy network address, for example `https://polygon-amoy.drpc.org`                      |
| `TITLE_CONTRACT`                                          | Optional. Address of the deployed `TitleRegistry` contract                                     |
| `PUBLIC_URL`                                              | Optional. The site's public address, used in QR codes and payment return links                 |
| `PAYSTACK_SECRET_KEY`                                     | Optional. Paystack **test** secret key (`sk_test_...`). Without it, online payment stays off   |
| `PRICE_INDIVIDUAL`, `PRICE_CORPORATE`                     | Optional. Token prices in naira (default 15000 and 200000)                                     |

Never commit your `.env` file. Keep the repository private while the project is not public.

## Hosting notes

- Render (free) runs the server. Point UptimeRobot at `/health` so it stays awake.
- Neon holds the PostGIS database. Run `schema_full.sql` on a new one, or the upgrade files on an existing one (`phase_j.sql` for this version, before deploying it: without it no admin or client can log in). The site keeps working before an upgrade is run; the new features just stay off.
- Add the new settings on Render (`TITLE_CONTRACT`, `PUBLIC_URL`, and `PAYSTACK_SECRET_KEY` when you have one). Set Paystack's webhook URL to `https://<your site>/api/pay/webhook`.
- `requirements.txt` now lists only what the server needs. Do not regenerate it with `pip freeze` (that adds `pywin32`, which breaks the Linux build).

## Limitations

- The ledger and anchoring prove a record has not changed since it was written. They do not prove the survey measurements were correct.
- Anchoring uses a **test network**. Records there are for demonstration only.
- Synthetic city plots are sample points, not surveyed land.
- There is no two-step login (2FA) and no password-reset email yet: an admin resets a client's password.
- Online payment is in Paystack test mode, and prices are provisional.
- Minna coordinates are converted with the standard Nigeria shift, good to a few metres, not centimetres.
- Rate limits live in the database (`rate_hits`); without `phase_j.sql` they fall back to server memory.

## Roadmap

- [x] Overlap checker and registration
- [x] CSV import and beacon photos
- [x] Hash-chained ledger
- [x] Polygon anchoring
- [x] Multi-city data and coordinate systems
- [x] Registry, report, About, How it works and Architecture pages
- [x] Client payment, login code, receipt and Register New Plot
- [x] Beacon photo upload for clients
- [x] Smart contract for title records (Amoy test network)
- [x] QR title verification and admin dashboard
- [x] Minna datum support and field data kit
- [x] Automatic tests
- [x] Admin and client accounts, rate limits kept in the database
- [x] Guided tour, simpler map and iPhone-style pages
- [ ] Payment gateway goes live (Paystack test mode is built; live after committee approval)
- [ ] Test with real survey data from the NAUB staff quarters

## Author

Built by Perey, for the SABAGeo research project at NAUB.
