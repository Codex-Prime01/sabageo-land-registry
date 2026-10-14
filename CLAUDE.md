# SABAGeo Land Registry: project notes for Claude

Handoff from the earlier claude.ai chat ("Building a web GIS land verification system"), checked against this repo on 14 Oct 2026. **This repo is the source of truth.** The old chat's file copies are out of date.

## What it is
Web-GIS land overlap checker with a tamper-evident record. Enter plot corners → **RED FLAG** (overlapping plots + overlap m²) or **0 OVERLAP** (green tick) → register and get a title code. Registered plots go into a SHA-256 hash-chained ledger; the latest hash can be anchored on **Polygon Amoy testnet**. Beacon photos: GPS EXIF is compared with the plot.

Built for a senior surveying student (Oga Alabi) at NAUB, Borno State, as research (TETFund, decentralized cadastre + blockchain). Company name on the site: **SABAGeo Technology Limited**.

- **Working prototype, not a legal registry.** Keep that honest in UI, README, About. No claims like "can never be faked". The ledger proves a record hasn't changed since written, not that the survey was right.
- **Confidential.** The senior asked to keep it secret: repo should be private. Never commit `.env`.
- Audience is students and a non-technical senior: **plain English everywhere** in the UI.

## Stack
PostgreSQL + PostGIS (psycopg 3) · FastAPI, single `main.py` (docs endpoints off) · plain HTML/CSS/JS + Leaflet (Esri satellite, OSM) · fonts Fraunces / Public Sans / IBM Plex Mono · dark/light theme · web3.py → Polygon Amoy · Pillow for EXIF, photos as BYTEA · hosted on Render (free, UptimeRobot pings `/health`) + Neon.

## Files
- `main.py`: the whole backend, fully merged (Phases C, D, E included).
- `schema.sql`: base tables for a fresh DB. `add_payments.sql`: payments/clients/login codes/sessions, `plots.client_id`, region `OTH`. Safe to re-run. **Fresh DB (e.g. Neon): run both, in that order.** (The old chat's `schema_full.sql`, `phase_d.sql`, `phase_e.sql` don't exist here.)
- `ingest_cities.py`: 55 synthetic plots (11 cities × 5). Expect `55 added`.
- `index.html` + `static/app.js` + `static/style.css`: the map page. `app.js` loads last as a classic script (not a module); inline `onclick`s need its globals. Don't rename the IDs it uses.
- Content pages: `registry`, `report`, `payments`, `receipt`, `register-plot`, `about`, `how-it-works`, `architecture` (`.html`). Each has its own inline CSS, plus shared `static/site.css` and `static/site.js`.
- **Page links live in one list: `PAGES` at the top of `static/site.js`** (top bar, ☰ drawer, footer). New page → add it there. The map page menu is built in `app.js` (grouping block at the end).

## Data model
- `regions`: NAUB (pilot, sorts first), LAG, ABJ, GMB, KAN, MDG, BIU, IBD, PHC, BEN, OWR, ILR, TST (test), OTH (clients' other locations).
- `plots`: title_code, region_code, source field|synthetic, status registered|reserved, label, cluster_type DISJOINT_NODE|ADJOINING_CLUSTER, ref_lat/lon, geom Polygon 4326 (GIST), area_m2, client_id.
- `ledger`, `photos`, `anchors`; payments side: `clients`, `payments`, `login_codes`, `client_sessions`, `receipt_seq` (TIMESTAMPTZ, because the code compares with UTC-aware datetimes).
- Title codes: pilot `SABA-NAUB-RES-001..005` (reserved up front, filled in order) · synthetic `SABA-<REGION>-SYN-NNN` · client `SABA-<REGION>-CLT-NNN`.

## Auth
Admin: header `X-Admin-Key` (key kept in `sessionStorage`, sent via `adminHeaders()`). Client: login code `SABA-XXXX-XXXX-XXXX` (only its hash stored, shown once) → `X-Client-Token` session, 12 h max. Wrong tries: 8 per 10 min, in memory. Receipts: receipt number + verify code. Payments are **simulated**. Optional `SITE_PASSWORD` gate must keep `/health` exempt.

## Decisions (don't undo without asking)
- **Store WGS84, measure in metres in local UTM** (`32600 + int((lon+180)//6) + 1`). Input: WGS84 or UTM 31/32/33.
- **Biu and Maiduguri are UTM 33N**, not 32N as the senior's doc says. Don't "fix" it back.
- **Touching is not overlap**: only intersection > 0.01 m² counts.
- Server re-checks overlap at registration; never trust the browser check.
- Nigeria bounding-box sanity check catches swapped lat/lon or wrong zone.
- Synthetic data is labelled synthetic; the 5 real NAUB pilot slots always come first.
- Cluster type and lat/long show in lists/registry only, **not on the map**. The dataset has points, not shapes, so stand-in rectangles are generated (DISJOINT sizes `[(18,28),(20,30),(24,32),(15,30),(22,26)]`; ADJOINING widths `[15,18,15,20,15]`, depth 30).
- Anchoring = zero-value self-tx with the hash in data, from a **test-only wallet**. Mainnet is a later decision.
- Architecture page labels things Built / Test / Planned. Keep it honest.

## Gotchas
- **`pywin32` breaks the Render (Linux) build.** `pip freeze` on Windows re-adds it; remove it from `requirements.txt` before pushing.
- **Don't use `rpc-amoy.polygon.technology`** (gave `NameResolutionError`). Default and `.env`/Render should be `https://polygon-amoy.drpc.org`. After env changes, do a full restart (`--reload` may miss them).
- New code using a new table/column → the DB needs a migration run too (`UndefinedTable` / `UndefinedColumn` = the code is ahead of the DB).
- `registerPlot`'s `.finally(...)` re-enables the button. It's load-bearing.
- `static/site.js` runs right after `</header>`, so anything below the header (like the footer) must wait for `DOMContentLoaded`.
- PowerShell 5.1 mangles `"` inside native-command args (git commit messages, `python -c`). Use here-strings without inner double quotes, or a script file.
- Rate limiter is in memory: resets on restart, not shared across instances.
- NAUB field data may be in **Minna datum**. Ask, don't assume WGS84.
- Never print or commit `ANCHOR_PRIVATE_KEY`, `ADMIN_KEY`, `SITE_PASSWORD`, `DATABASE_URL`.

## Run
```
venv\Scripts\activate
pip install -r requirements.txt
# fresh DB: run schema.sql, then add_payments.sql; copy .env.example to .env
python ingest_cities.py      # 55 added
uvicorn main:app --reload    # http://127.0.0.1:8000
```
`.env`: `DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD` (or `DATABASE_URL`), `ADMIN_KEY`, `SITE_PASSWORD` (optional), `ANCHOR_PRIVATE_KEY`, `POLYGON_RPC`.

## Smoke test
1. Every menu link opens its page (map drawer, top bar, ☰ on content pages).
2. Overlapping polygon → red X; clear → green tick; edge-touching must **not** flag.
3. Admin key → register a plot, upload a photo, `/ledger/verify`, `/ledger/anchor`, confirm the tx on Amoy.
4. Payment flow: admin records payment → client logs in with code → registers via `/register-plot` → receipt verifies.
5. Phone width: bottom sheet and menus work.

## Planned next
1. Split `main.py` into modules + add tests.
2. Client beacon-photo upload (admin-only today).
3. Real payment gateway (amount, company, client details not yet decided).
4. Real NAUB field data (fill the 5 slots; datum/zone decision).
5. Real user accounts/roles instead of a shared admin key; persistent rate limiting.
6. Smart contract for title records; mainnet vs testnet.
7. README screenshots.

**Open questions for the senior:** stand-in plot sizes, adjoining layout, payment amount/company, client details to collect, About us wording, NAUB datum/zone.
