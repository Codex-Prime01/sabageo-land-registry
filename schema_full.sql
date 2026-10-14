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
