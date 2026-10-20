-- SABAGeo Land Registry: database setup (version 3)
-- For a NEW, empty database. Plots are stored in WGS84 (EPSG:4326).
-- Areas and overlaps are measured in metres by converting to the plot's local UTM zone.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Areas the platform covers. The pilot area always sorts first.
CREATE TABLE regions (
  code       TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  sort_order INTEGER NOT NULL,
  is_pilot   BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO regions (code, name, sort_order, is_pilot) VALUES
  ('NAUB', 'NAUB Pilot, Biu (real field data)', 0,  TRUE),
  ('LAG',  'Ikeja, Lagos State',                1,  FALSE),
  ('ABJ',  'Abuja, FCT',                        2,  FALSE),
  ('GMB',  'Gombe, Gombe State',                3,  FALSE),
  ('KAN',  'Kano, Kano State',                  4,  FALSE),
  ('MDG',  'Maiduguri, Borno State',            5,  FALSE),
  ('BIU',  'Borno-Biu Emirate, Borno State',    6,  FALSE),
  ('IBD',  'Ibadan, Oyo State',                 7,  FALSE),
  ('PHC',  'Port Harcourt, Rivers State',       8,  FALSE),
  ('BEN',  'Benin City, Edo State',             9,  FALSE),
  ('OWR',  'Owerri, Imo State',                 10, FALSE),
  ('ILR',  'Ilorin, Kwara State',               11, FALSE),
  ('TST',  'Test area',                         99, FALSE);

-- Land plots. A "reserved" plot is an empty slot waiting for real measurements (geom is empty).
-- cluster_type is the senior's notation for the localized dataset:
--   DISJOINT_NODE      separate parcels
--   ADJOINING_CLUSTER  parcels that touch along shared boundaries
-- ref_lat / ref_lon is the coordinate the plot has in the dataset table.
CREATE TABLE plots (
  id            SERIAL PRIMARY KEY,
  title_code    TEXT UNIQUE NOT NULL,
  region_code   TEXT NOT NULL REFERENCES regions(code),
  source        TEXT NOT NULL DEFAULT 'field',        -- 'field' or 'synthetic'
  status        TEXT NOT NULL DEFAULT 'registered',   -- 'registered' or 'reserved'
  label         TEXT,
  cluster_type  TEXT CHECK (cluster_type IN ('DISJOINT_NODE', 'ADJOINING_CLUSTER')),
  ref_lat       DOUBLE PRECISION,
  ref_lon       DOUBLE PRECISION,
  geom          geometry(Polygon, 4326),
  area_m2       DOUBLE PRECISION,
  registered_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX plots_geom_idx ON plots USING GIST (geom);

-- The 5 NAUB pilot slots. They are created first, so the pilot area comes first.
INSERT INTO plots (title_code, region_code, source, status, label)
SELECT 'SABA-NAUB-RES-' || LPAD(g::text, 3, '0'), 'NAUB', 'field', 'reserved', 'Pilot plot ' || g
FROM generate_series(1, 5) AS g;

-- Hash-chained ledger: every record holds the fingerprint of the one before it
CREATE TABLE ledger (
  id          SERIAL PRIMARY KEY,
  title_code  TEXT NOT NULL,
  payload     TEXT NOT NULL,
  prev_hash   TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  created_at  TIMESTAMP DEFAULT NOW()
);

-- Geotagged beacon photos (shrunk, kept in the database)
CREATE TABLE photos (
  id           SERIAL PRIMARY KEY,
  title_code   TEXT NOT NULL REFERENCES plots(title_code),
  filename     TEXT NOT NULL,
  lat          DOUBLE PRECISION,
  lon          DOUBLE PRECISION,
  distance_m   DOUBLE PRECISION,
  data         BYTEA,
  content_type TEXT,
  uploaded_at  TIMESTAMP DEFAULT NOW()
);

-- Ledger fingerprints posted on the Polygon Amoy test network
CREATE TABLE anchors (
  id           SERIAL PRIMARY KEY,
  ledger_id    INTEGER NOT NULL,
  record_hash  TEXT NOT NULL,
  tx_hash      TEXT NOT NULL,
  block_number BIGINT,
  anchored_at  TIMESTAMP DEFAULT NOW()
);

-- SABAGeo Land Registry: Phase D (client payments, login codes, receipts)
-- Safe to run on your existing database. Nothing is deleted.
-- Also paste it at the end of schema.sql, so a brand new database gets these tables too.

-- People who pay for access (kept to the minimum: a name, a type, optional contact)
CREATE TABLE IF NOT EXISTS clients (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  client_type TEXT NOT NULL CHECK (client_type IN ('individual', 'corporate')),
  email       TEXT,
  phone       TEXT,
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE SEQUENCE IF NOT EXISTS receipt_seq START 1;

-- One row per token payment. Also acts as the receipt.
CREATE TABLE IF NOT EXISTS payments (
  id          SERIAL PRIMARY KEY,
  client_id   INTEGER NOT NULL REFERENCES clients(id),
  receipt_no  TEXT UNIQUE NOT NULL,
  verify_code TEXT NOT NULL,
  amount_ngn  NUMERIC(14, 2) NOT NULL CHECK (amount_ngn > 0),
  method      TEXT NOT NULL,
  reference   TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'void')),
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- The same payment reference can only be recorded once
CREATE UNIQUE INDEX IF NOT EXISTS payments_reference_uq ON payments (lower(reference));

-- Login codes. Only a fingerprint of each code is stored, never the code itself.
CREATE TABLE IF NOT EXISTS login_codes (
  id            SERIAL PRIMARY KEY,
  payment_id    INTEGER NOT NULL REFERENCES payments(id),
  client_id     INTEGER NOT NULL REFERENCES clients(id),
  code_hash     TEXT UNIQUE NOT NULL,
  expires_at    TIMESTAMPTZ NOT NULL,
  plots_allowed INTEGER,               -- empty means no limit
  plots_used    INTEGER NOT NULL DEFAULT 0,
  revoked       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Short-lived sessions, created when a client logs in with a code
CREATE TABLE IF NOT EXISTS client_sessions (
  id         SERIAL PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  code_id    INTEGER NOT NULL REFERENCES login_codes(id),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Which client registered a plot (used by the Register New Plot page in the next phase)
ALTER TABLE plots ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id);

-- SABAGeo Land Registry: Phase E (Register New Plot for clients)
-- Safe to run on your existing database. Nothing is deleted.
-- Also paste it at the end of schema.sql.

-- Clients can be anywhere in Nigeria, so they need a region for land outside the dataset cities.
INSERT INTO regions (code, name, sort_order, is_pilot)
VALUES ('OTH', 'Other locations, Nigeria', 90, FALSE)
ON CONFLICT (code) DO NOTHING;

-- SABAGeo Land Registry: Phase G (owner details for Register New Plot)
-- Safe to run on your existing database. Nothing is deleted.
-- schema_full.sql already includes this, so a brand new database does not need it.

-- Who the plot belongs to. A corporate retainer can register plots for its own buyers,
-- so the owner can be different from the client who paid.
-- Phone and email are never shown on public pages.
ALTER TABLE plots ADD COLUMN IF NOT EXISTS owner_type  TEXT CHECK (owner_type IN ('individual', 'corporate'));
ALTER TABLE plots ADD COLUMN IF NOT EXISTS owner_name  TEXT;
ALTER TABLE plots ADD COLUMN IF NOT EXISTS owner_phone TEXT;
ALTER TABLE plots ADD COLUMN IF NOT EXISTS owner_email TEXT;

-- SABAGeo Land Registry: Phase H (dashboard, on-chain titles, Minna datum)
-- Safe to run on your existing database, and safe to run more than once. Nothing is deleted.
-- Run it on Neon too. The website keeps working before it is run; these features just stay off.

-- One row per overlap check, for the admin dashboard. No coordinates or personal details.
CREATE TABLE IF NOT EXISTS check_log (
  id            SERIAL PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  region_code   TEXT,
  status        TEXT NOT NULL CHECK (status IN ('RED FLAG', '0 OVERLAP')),
  overlap_count INTEGER NOT NULL DEFAULT 0,
  overlap_m2    DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS check_log_created_idx ON check_log (created_at);

-- Title records written to the TitleRegistry smart contract on Polygon Amoy.
-- One row per title: the latest ledger record that is on-chain for it.
CREATE TABLE IF NOT EXISTS chain_titles (
  title_code  TEXT PRIMARY KEY,
  ledger_id   INTEGER NOT NULL,
  record_hash TEXT NOT NULL,
  action      TEXT NOT NULL DEFAULT 'record' CHECK (action IN ('record', 'remove')),
  tx_hash     TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Online payments (Paystack). One row per attempt, written BEFORE the customer is sent to
-- Paystack, so the amount we expect never comes from the browser.
CREATE TABLE IF NOT EXISTS pay_intents (
  reference   TEXT PRIMARY KEY,
  plan        TEXT NOT NULL CHECK (plan IN ('individual', 'corporate')),
  name        TEXT NOT NULL,
  email       TEXT NOT NULL,
  phone       TEXT,
  amount_kobo BIGINT NOT NULL CHECK (amount_kobo > 0),
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'failed')),
  receipt_no  TEXT,
  code_shown  BOOLEAN NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at     TIMESTAMPTZ
);

-- Minna datum, UTM zone 33N (Biu, Maiduguri). PostGIS has Minna 31N and 32N but not 33N,
-- so it is added here with the standard Nigeria shift to WGS84 (Clarke 1880, -92 -93 122).
-- Wrapped so a database that does not allow it simply skips it (the choice then stays off).
DO $$
BEGIN
  INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text)
  VALUES (926333, 'SABAGeo', 926333, '',
          '+proj=utm +zone=33 +ellps=clrk80 +towgs84=-92,-93,122,0,0,0,0 +units=m +no_defs')
  ON CONFLICT (srid) DO NOTHING;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'Could not add Minna / UTM 33N (no permission). Everything else is fine.';
END $$;

-- SABAGeo Land Registry: Phase I (one Individual code = one plot)
-- Safe to run on your existing database, and safe to run more than once. Nothing is deleted.
-- Run it on Neon too, before deploying the code. Without it the site still works, but
-- Individual codes are not locked to one plot.

-- The plot a single-plot login code is locked to: set the first time the code checks a plot.
-- Stored as WGS84 text (the same form as the ledger), so it can be compared with later checks.
ALTER TABLE login_codes ADD COLUMN IF NOT EXISTS bound_wkt TEXT;
ALTER TABLE login_codes ADD COLUMN IF NOT EXISTS bound_at  TIMESTAMPTZ;

-- SABAGeo Land Registry: Phase J (admin accounts and client accounts instead of one shared admin key)
-- Safe to run on your existing database, and safe to run more than once. Nothing is deleted.
-- Run it on Neon BEFORE deploying the code: without it no admin or client account can log in.
-- Then make the first admin account with:  python tools/create_staff.py

-- One row per admin. Only a scrypt hash of the password is kept, never the password.
CREATE TABLE IF NOT EXISTS staff (
  id            SERIAL PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL CHECK (username = lower(username)),
  name          TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  last_login_at TIMESTAMPTZ
);

-- Logged-in admins (12 hours max). Disabling someone deletes their sessions.
CREATE TABLE IF NOT EXISTS staff_sessions (
  id         SERIAL PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  staff_id   INTEGER NOT NULL REFERENCES staff(id),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Who did what: one row per admin action (register, payment, void, anchor, ...).
CREATE TABLE IF NOT EXISTS staff_log (
  id         SERIAL PRIMARY KEY,
  staff_id   INTEGER NOT NULL REFERENCES staff(id),
  action     TEXT NOT NULL,
  target     TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS staff_log_time_idx ON staff_log (created_at DESC);

-- Client accounts (like a shop account): email + password. Clients see their own receipts and plots,
-- start Register New Plot without typing a code, and get a fresh login code themselves.
-- Only a scrypt hash of the password is kept. Admins can reset a forgotten password.
CREATE TABLE IF NOT EXISTS accounts (
  id            SERIAL PRIMARY KEY,
  email         TEXT UNIQUE NOT NULL CHECK (email = lower(email)),
  name          TEXT NOT NULL,
  phone         TEXT,
  password_hash TEXT NOT NULL,
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  last_login_at TIMESTAMPTZ
);

-- Logged-in clients (7 days max). Disabling an account deletes its sessions.
CREATE TABLE IF NOT EXISTS account_sessions (
  id         SERIAL PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Which account a payment's client belongs to (empty for payments nobody has claimed yet).
ALTER TABLE clients ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id);
CREATE INDEX IF NOT EXISTS clients_account_idx ON clients (account_id);
-- An online payment started while logged in goes into that account.
ALTER TABLE IF EXISTS pay_intents ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id);

-- Rate limits kept in the database, so they survive a restart and work on more than one server.
-- Optional: without this table the limits fall back to server memory.
CREATE TABLE IF NOT EXISTS rate_hits (
  id      BIGSERIAL PRIMARY KEY,
  bucket  TEXT NOT NULL,
  visitor TEXT NOT NULL,
  hit_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rate_hits_lookup_idx ON rate_hits (bucket, visitor, hit_at);
