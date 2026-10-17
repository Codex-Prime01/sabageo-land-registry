# SABAGeo Land Registry: project notes for Claude

Handoff from the earlier claude.ai chat ("Building a web GIS land verification system"), checked against this repo on 14 Oct 2026 and updated after Phase H. **This repo is the source of truth.** The old chat's file copies are out of date.

## What it is
Web-GIS land overlap checker with a tamper-evident record. Enter plot corners → **RED FLAG** (overlapping plots + overlap m², zone shaded) or **0 OVERLAP** → register and get a title code. Registered plots go into a SHA-256 hash-chained ledger; the latest hash can be anchored on **Polygon Amoy testnet**, and each title's latest record can be written to the **TitleRegistry** smart contract. Parcel reports carry a QR code to a public verify page. Beacon photos: GPS EXIF is compared with the plot.

Built for a senior surveying student (Oga Alabi) at NAUB, Borno State, as research (TETFund, decentralized cadastre + blockchain). Company name on the site: **SABAGeo Technology Limited**.

- **Working prototype, not a legal registry.** Keep that honest in UI, README, About. No claims like "can never be faked". The ledger proves a record hasn't changed since written, not that the survey was right.
- **Confidential.** The senior asked to keep it secret: repo should be private. Never commit `.env`.
- Audience is students and a non-technical senior: **plain English everywhere** in the UI.

## Stack
PostgreSQL + PostGIS (psycopg 3) · FastAPI (docs endpoints off) · plain HTML/CSS/JS + Leaflet (Esri satellite, OSM) · fonts Fraunces / Public Sans / IBM Plex Mono · dark/light theme · web3.py → Polygon Amoy · Pillow for EXIF, photos as BYTEA · segno for QR SVGs · Paystack (test mode) via requests · hosted on Render (free, UptimeRobot pings `/health`) + Neon.

## Code layout
- `main.py`: thin entry. Builds the app, site-password middleware, includes the routers. **Re-exports `app`, `DB`, `find_overlaps`, `next_code`, `add_ledger_record`, `add_removal_record`** because `ingest_cities.py`, `reset_dataset.py` and the tests use `main.<name>`. Keep those.
- `sabageo/`: `config.py` (env, CRS_CHOICES, GEOGRAPHIC, PLANS, `paystack_key()`, PUBLIC_URL, RPC) · `db.py` (`connect()` reads `config.DB` at call time, so tests can repoint it) · `security.py` (admin key, client sessions, `check_limit`/`record_fail`, `throttle`) · `geo.py` · `ledger.py` (`verify_chain`) · `photos.py` (`read_upload`, `save_photo`, shared by admin and client) · `codes.py` (login codes, `create_payment`, shared by admin form and Paystack) · `chain.py` (TitleRegistry helpers, `onchain_title`).
- `sabageo/routes/`: pages, plots (map data, `/check` + check_log, register, admin photos), ledger (verify, anchor), chain (sync-titles, live chain check), payments, paystack, clients (login, register, client photos), verify (QR page + API), admin (dashboard).
- `contracts/TitleRegistry.sol` + compiled `TitleRegistry.json` (the server only reads the JSON). `tools/compile_contract.py` (dev, py-solc-x), `tools/deploy_contract.py` (refuses any chain but Amoy 80002).
- Pages: `index.html` (map) + `static/app.js` + `static/style.css`; content pages `registry report receipt register-plot verify field-kit admin admin-payments about how-it-works architecture` (.html), each with inline CSS + shared `static/site.css` / `static/site.js`. `static/csv.js` = shared CSV corner reader (map + Register New Plot).
- **Payment flow (Spotify-style, one job per screen):** `/payments` = plans only (`payments.html`) → `/pay/individual` or `/pay/corporate` = checkout (`pay.html`) → Paystack → `/receipt/...#code=` → **"Start registering my plot"** → `/register-plot#code=` logs in by itself and wipes the code from the address bar. Both flow pages use `static/flow.css`. Staff tools (record payment, payments list, check a code) live at **`/admin/payments`** (`admin-payments.html`), never on the public page (a test enforces this).
- **Look:** flat. Solid surfaces (`--card` is solid in site.css), no glass blur, no card borders/shadows/corner marks, pill buttons, brass used sparingly. The map page keeps its own floating-panel style.
- **Page links live in `PAGES` in `static/site.js`** (top bar, ☰ drawer, footer) **and `MENU` in `static/app.js`** (map drawer). New page → add to both.
- DB: **fresh DB → `schema_full.sql` only** (includes everything through Phase I). Existing DB → `add_payments.sql`, `phase_g.sql`, `phase_h.sql`, `phase_i.sql` in order; all additive and safe to re-run.
- Data scripts: `ingest_cities.py` (55 synthetic 18 × 30 m plots), `reset_dataset.py` (dry run unless `--go`).

## Tests
`pip install -r requirements-dev.txt` then `python -m pytest` (103+ tests). `tests/conftest.py` builds a separate local **`sabageo_test`** DB from `schema_full.sql` + `phase_h.sql`, truncates before each test, refuses non-local DB hosts, and **unsets PAYSTACK/TITLE_CONTRACT/ANCHOR_PRIVATE_KEY/PUBLIC_URL** so tests never hit real services. Paystack and the chain are faked in tests. `test_chain.py` in the repo root is a network script, not a test (pytest.ini limits to `tests/`).

## Data model
- `regions`: NAUB (pilot, sorts first), LAG, ABJ, GMB, KAN, MDG, BIU, IBD, PHC, BEN, OWR, ILR, TST (test), OTH (clients' other locations).
- `plots`: title_code, region_code, source field|synthetic, status registered|reserved, label, cluster_type, ref_lat/lon, geom Polygon 4326 (GIST), area_m2, client_id, owner_type/name/phone/email. **Owner phone and email are private: only `/api/admin/overview` (admin) returns them.**
- Ledger payloads: registration `{title_code, wkt, area_m2, time}` or removal `{title_code, action: "removed", reason, time}`. Never edit or delete ledger rows; append a removal.
- `ledger`, `photos`, `anchors`; payments: `clients`, `payments`, `login_codes`, `client_sessions`, `receipt_seq` (TIMESTAMPTZ).
- Phase H (`phase_h.sql`): `check_log` (one row per /check, no coordinates), `chain_titles` (latest ledger record per title that is on-chain), `pay_intents` (Paystack attempts; expected amount stored server-side), SRID **926333 = Minna / UTM 33N**.
- **Every Phase H table is optional at runtime**: code catches `UndefinedTable` in a savepoint, so a DB without `phase_h.sql` keeps working with those features off.
- Title codes: pilot `SABA-NAUB-RES-001..005` · synthetic `SABA-<REGION>-SYN-NNN` · client `SABA-<REGION>-CLT-NNN`.

## Auth and security
- Admin: header `X-Admin-Key` (sessionStorage `adminKey`). Client: login code (hash only, shown once) → `X-Client-Token`, 12 h max (sessionStorage `clientToken`).
- In-memory limits: wrong codes/receipts 8 per 10 min; `/api/pay/start` 10 per 10 min; live chain check 30 per 10 min.
- Client photos: only on the client's own plot (404 otherwise, so codes can't be probed), max 5 per plot, row lock on the count.
- Paystack: live key (`sk_live_`) refused unless `PAYSTACK_LIVE=1`; verify status + amount (vs pay_intents) + currency on Paystack's server; webhook needs HMAC-SHA512 signature; intent row `FOR UPDATE` so one intent = one payment; the login code is shown once (callback re-issues if the webhook recorded it first).
- Chain: `connect_chain()` refuses any chain id but 80002. Contract writes are owner-only and idempotent (older/equal ledgerId skipped), so a resend after a crash is harmless.
- Admin CSV export escapes formula-leading cells. All page JS escapes server data before innerHTML.

## Decisions (don't undo without asking)
- **Store WGS84, measure in metres in local UTM** (`32600 + int((lon+180)//6) + 1`).
- **Biu and Maiduguri are UTM 33N** (Benin City is 31N). Don't "fix" it back.
- **Minna supported** (lat/long 4263, UTM 31/32N 26331/26332, UTM 33N custom 926333 with towgs84 -92,-93,122, belts 26391–3). Same recipe matches official EPSG:26332 to 0.00 m. UI says it is good to a few metres. Still ask Oga which datum the NAUB data uses.
- **Touching is not overlap**: > 0.01 m² AND survives a negative buffer of half `OVERLAP_TOLERANCE_CM` (10 cm).
- **Overlap location is shown, not a badge**. Perey asked to remove the big tick/X map badge; don't add it back.
- Token prices (provisional): ₦15,000 individual, ₦200,000 corporate per month (no limit, 30 days). `PRICE_INDIVIDUAL` / `PRICE_CORPORATE`.
- **Individual code = ONE plot, valid 3 days** (Oga, 16 Oct). A code with `plots_allowed = 1` is locked to the first plot it checks or registers (`login_codes.bound_wkt`, `phase_i.sql`); re-checks must be the same plot (Hausdorff ≤ `SAME_PLOT_TOLERANCE_M`, 3 m), anything else is 403. Register New Plot checks via `POST /client/check` (needs a client token), not the public `/check`. Staff can clear a lock for a genuine mistake: "Unlock plot" on `/admin/payments` (`POST /api/admin/payments/{receipt}/unlock-plot`). The map's public `/check` stays free (Perey's decision).
- **The name is "SABAGeo"**, never SABAGEO. Don't put it in all-caps styled text (th, .eyebrow, .kicker, .sx-label) without `class="keep-case"`; `tests/test_branding.py` enforces it.
- Server re-checks overlap at registration. Nigeria bounding box after conversion. Synthetic data labelled; NAUB pilot slots first.
- Cluster type and lat/long only in lists, not on the map. No other "six zones" dataset exists.
- Anchoring and title records use a **test-only wallet** on Amoy. Mainnet is a later decision.
- Architecture page labels Built / Test / Planned honestly (QR = Built, smart contract = Test network).

## Live test-network state (14 Oct 2026)
- TitleRegistry deployed at `0x00af627898d4aFE65Ee6817969F0504ebce1BEC6` (owner = the anchor wallet). In local `.env` as `TITLE_CONTRACT`.
- 2 titles written in a live test (SABA-OTH-CLT-001, SABA-LAG-SYN-001); `chain_titles` was not updated by that test, so the next sync resends them and the contract skips them.
- Wallet had ~0.061 test POL left. A full sync of ~61 titles needs ~0.14: top up from the Amoy faucet.

## Gotchas
- **Don't regenerate `requirements.txt` with `pip freeze`** (adds `pywin32`, breaks Render). It's hand-kept and UTF-8.
- **Don't use `rpc-amoy.polygon.technology`**. Use `https://polygon-amoy.drpc.org`. After `.env` changes, fully restart uvicorn (`--reload` only reloads code).
- New code using a new table/column → the DB needs a migration too. **Run the migration before deploying the code.**
- `eth-tester` can't build on Python 3.14 (safe-pysha3), so there is no local EVM: contract logic is tested by a Python model + a live Amoy run.
- `registerPlot`'s `.finally(...)` re-enables the button. It's load-bearing.
- **Never add a catch-all route like `/pay/{plan}`**: it swallowed `/pay/callback` (Paystack's return address). Checkout routes are exact; a new plan needs its own route line in `routes/pages.py`.
- **Duplicate HTML ids break pages silently** (getElementById returns the first). A test checks every page.
- `static/site.js` runs right after `</header>`: anything below it must wait for `DOMContentLoaded`.
- PowerShell 5.1 mangles `"` inside native-command args. Use here-strings without inner double quotes, or a script file. Long bash heredocs with many quotes can fail too: write a script file.
- Rate limits are in memory: reset on restart, not shared across instances.
- Never print or commit `ANCHOR_PRIVATE_KEY`, `ADMIN_KEY`, `SITE_PASSWORD`, `DATABASE_URL`, `PAYSTACK_SECRET_KEY`.

## Run
```
venv\Scripts\activate
pip install -r requirements.txt          # requirements-dev.txt for tests
# fresh DB: schema_full.sql; existing: add_payments.sql, phase_g.sql, phase_h.sql
python ingest_cities.py      # 55 added
uvicorn main:app --reload    # http://127.0.0.1:8000
```
`.env`: see `.env.example` (DB, ADMIN_KEY, SITE_PASSWORD, ANCHOR_PRIVATE_KEY, POLYGON_RPC, TITLE_CONTRACT, PUBLIC_URL, PAYSTACK_SECRET_KEY, prices).

## Smoke test
1. Every menu link opens its page (map drawer, top bar, ☰ on content pages).
2. Overlap → red flag with shaded zone; clear → 0 OVERLAP; edge-touching must **not** flag. Try a Minna type and the field kit CSV template.
3. Admin key → register, upload a photo, `/ledger/verify`, anchor, **Write titles to contract**, then `/verify/<code>` shows "checked live".
4. Payments: admin records one → client logs in → registers → adds a beacon photo → receipt verifies. With a Paystack test key: Pay online → test card → back on the receipt with a code.
5. `/admin` with the admin key shows the client plot, payment and check counts.
6. Phone width: bottom sheet and menus work.

## Planned next
0. **Live site:** run `phase_h.sql` on Neon (and `reset_dataset.py` dry run → `--go` with Perey's OK, for the old Maiduguri/Biu leftovers). Add `TITLE_CONTRACT`, `PUBLIC_URL`, `PAYSTACK_SECRET_KEY` on Render; Paystack webhook → `/api/pay/webhook`.
1. Real NAUB field data (fill the 5 slots; datum answer from Oga).
2. Payment gateway live (after committee approval; company not chosen).
3. Real user accounts/roles instead of a shared admin key; persistent rate limiting.
4. Mainnet vs testnet decision. README screenshots.

**Answered by the senior (12 Oct):** receipt design, token-first flow, provisional prices, printable report, Register New Plot fields, 18 × 30 plots, "use the method that gives the most suitable results".
**Still open:** NAUB datum/zone, payment gateway company, SABAGeo contact details for /payments, whether the public report should show the owner name (currently yes, name only).
