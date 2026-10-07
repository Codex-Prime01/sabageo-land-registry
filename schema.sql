-- SABAGeo Land Registry: database setup (version 2)
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
  ('NAUB', 'NAUB Pilot, Biu (real field data)', 0, TRUE),
  ('LAG',  'Ikeja, Lagos State',                1, FALSE),
  ('ABJ',  'Abuja, FCT',                        2, FALSE),
  ('GMB',  'Gombe, Gombe State',                3, FALSE),
  ('KAN',  'Kano, Kano State',                  4, FALSE),
  ('MDG',  'Maiduguri, Borno State',            5, FALSE),
  ('BIU',  'Biu Emirate, Borno State',          6, FALSE),
  ('TST',  'Test area',                        99, FALSE);

-- Land plots. A "reserved" plot is an empty slot waiting for real measurements (geom is empty).
CREATE TABLE plots (
  id            SERIAL PRIMARY KEY,
  title_code    TEXT UNIQUE NOT NULL,
  region_code   TEXT NOT NULL REFERENCES regions(code),
  source        TEXT NOT NULL DEFAULT 'field',        -- 'field' or 'synthetic'
  status        TEXT NOT NULL DEFAULT 'registered',   -- 'registered' or 'reserved'
  label         TEXT,
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