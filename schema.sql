-- SABAGeo Land Registry: database setup
-- Run this once on a new PostgreSQL database (pgAdmin Query Tool, or psql).
-- All plot geometry is stored in WGS 84 / UTM Zone 32N (EPSG:32632), in metres.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Registered land plots
CREATE TABLE IF NOT EXISTS plots (
  id            SERIAL PRIMARY KEY,
  title_code    TEXT UNIQUE NOT NULL,
  geom          geometry(Polygon, 32632) NOT NULL,
  area_m2       DOUBLE PRECISION,
  registered_at TIMESTAMP DEFAULT NOW()
);

-- Makes the overlap check fast when there are many plots
CREATE INDEX IF NOT EXISTS plots_geom_idx ON plots USING GIST (geom);

-- Counter for title codes: SABA-NAUB-RES-001, 002, ...
CREATE SEQUENCE IF NOT EXISTS plot_code_seq START 1;

-- Hash-chained ledger: every record holds the fingerprint of the one before it
CREATE TABLE IF NOT EXISTS ledger (
  id          SERIAL PRIMARY KEY,
  title_code  TEXT NOT NULL,
  payload     TEXT NOT NULL,
  prev_hash   TEXT NOT NULL,
  record_hash TEXT NOT NULL,
  created_at  TIMESTAMP DEFAULT NOW()
);

-- Geotagged beacon photos
CREATE TABLE IF NOT EXISTS photos (
  id          SERIAL PRIMARY KEY,
  title_code  TEXT NOT NULL REFERENCES plots(title_code),
  filename    TEXT NOT NULL,
  lat         DOUBLE PRECISION,
  lon         DOUBLE PRECISION,
  distance_m  DOUBLE PRECISION,
  uploaded_at TIMESTAMP DEFAULT NOW()
);

-- Ledger fingerprints posted on the Polygon Amoy test network
CREATE TABLE IF NOT EXISTS anchors (
  id           SERIAL PRIMARY KEY,
  ledger_id    INTEGER NOT NULL,
  record_hash  TEXT NOT NULL,
  tx_hash      TEXT NOT NULL,
  block_number BIGINT,
  anchored_at  TIMESTAMP DEFAULT NOW()
);
