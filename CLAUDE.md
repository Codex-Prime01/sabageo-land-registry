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
- **Fresh DB (e.g. Neon): run `schema_full.sql` only.** Existing DB: `add_payments.sql` (payments, clients, login codes, sessions, `plots.client_id`, region OTH) then `phase_g.sql` (owner columns). Both are safe to re-run. `schema.sql` is the old base file.
- `ingest_cities.py`: 55 synthetic plots (11 cities × 5), all **18 m × 30 m** (the senior's standard plot). Expect `55 added`.
- `reset_dataset.py`: **dry run by default**; `--go` removes every synthetic plot (writing ledger "removed" records) and reloads the 55. Real field/client plots are kept unless named with `--remove CODE`.
- `index.html` + `static/app.js` + `static/style.css`: the map page. `app.js` (Phase G rewrite) loads last as a classic script (not a module); inline `onclick`s need its globals. Don't rename the IDs it uses. Its map menu is built from `MENU` (groups) in `buildMenu()`.
- Content pages: `registry`, `report`, `payments`, `receipt`, `register-plot`, `about`, `how-it-works`, `architecture` (`.html`). Each has its own inline CSS, plus shared `static/site.css` and `static/site.js`.
- **Page links live in one list: `PAGES` at the top of `static/site.js`** (top bar, ☰ drawer, footer). New page → add it there AND to `MENU` in `app.js`. The 8 pages hard-code a fallback `<nav>` that site.js replaces.

## Data model
- `regions`: NAUB (pilot, sorts first), LAG, ABJ, GMB, KAN, MDG, BIU, IBD, PHC, BEN, OWR, ILR, TST (test), OTH (clients' other locations).
- `plots`: title_code, region_code, source field|synthetic, status registered|reserved, label, cluster_type DISJOINT_NODE|ADJOINING_CLUSTER, ref_lat/lon, geom Polygon 4326 (GIST), area_m2, client_id, owner_type/name/phone/email. **Owner phone and email are private: never return them from public endpoints.**
- Ledger payloads: a registration `{title_code, wkt, area_m2, time}` or a removal `{title_code, action: "removed", reason, time}`. Never edit or delete ledger rows; append a removal instead.
- `ledger`, `photos`, `anchors`; payments side: `clients`, `payments`, `login_codes`, `client_sessions`, `receipt_seq` (TIMESTAMPTZ, because the code compares with UTC-aware datetimes).
- Title codes: pilot `SABA-NAUB-RES-001..005` (reserved up front, filled in order) · synthetic `SABA-<REGION>-SYN-NNN` · client `SABA-<REGION>-CLT-NNN`.

## Auth
Admin: header `X-Admin-Key` (key kept in `sessionStorage`, sent via `adminHeaders()`). Client: login code `SABA-XXXX-XXXX-XXXX` (only its hash stored, shown once) → `X-Client-Token` session, 12 h max. Wrong tries: 8 per 10 min, in memory. Receipts: receipt number + verify code. Payments are **simulated**. Optional `SITE_PASSWORD` gate must keep `/health` exempt.

## Decisions (don't undo without asking)
- **Store WGS84, measure in metres in local UTM** (`32600 + int((lon+180)//6) + 1`). Input: WGS84 or UTM 31/32/33.
- **Biu and Maiduguri are UTM 33N**, not 32N as the senior's doc says. Don't "fix" it back.
- **Touching is not overlap**: intersection must be > 0.01 m² AND survive a negative buffer of half `OVERLAP_TOLERANCE_CM` (default 10 cm), so rounding slivers don't flag. Tested: 220 self re-checks across 4 CRS, 0 neighbour hits.
- **Overlap location is shown, not a badge**: `/check` returns per hit the zone GeoJSON, m², % of that plot and centre; the map shades the zone with a label and a Show button. Perey asked to remove the big tick/X map badge, so don't add it back.
- Token prices (provisional, pending the review committee): ₦15,000 individual per verification (1 plot, 30 days), ₦200,000 corporate per month (no limit). Set via `PRICE_INDIVIDUAL` / `PRICE_CORPORATE` in `.env`; served at `/api/prices`.
- Server re-checks overlap at registration; never trust the browser check.
- Nigeria bounding-box sanity check catches swapped lat/lon or wrong zone.
- Synthetic data is labelled synthetic; the 5 real NAUB pilot slots always come first.
- Cluster type and lat/long show in lists/registry only, **not on the map**. The dataset has points, not shapes, so stand-in 18 × 30 m rectangles are generated (18 m east-west). DISJOINT (LAG, ABJ, KAN, GMB, MDG, BIU): centred on each point. ADJOINING (IBD, PHC, BEN, OWR, ILR): a touching row anchored at Plot 1. There is no other "six zones" dataset.
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
# fresh DB: run schema_full.sql; copy .env.example to .env
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
0. **Live site (Neon) still has the old Maiduguri/Biu leftovers.** Run `phase_g.sql` there, then `reset_dataset.py` dry run against Neon, review, then `--go` (with Perey's OK).
1. Split `main.py` into modules + add tests.
2. Client beacon-photo upload (admin-only today).
3. Real payment gateway (amount, company, client details not yet decided).
4. Real NAUB field data (fill the 5 slots; datum/zone decision).
5. Real user accounts/roles instead of a shared admin key; persistent rate limiting.
6. Smart contract for title records; mainnet vs testnet.
7. README screenshots.

**Answered by the senior (12 Oct):** receipt design (SABAGeo letterhead, code like an MTN card), token-first flow, provisional prices, printable report (shape, perimeter, area, map), Register New Plot fields, 18 × 30 plots, "use the method that gives the most suitable results".
**Still open:** NAUB datum/zone, payment gateway company, SABAGeo contact details for /payments, whether the public report should show the owner name (currently yes, name only).
