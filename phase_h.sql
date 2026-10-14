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

-- Minna datum, UTM zone 33N (Biu, Maiduguri). PostGIS has Minna 31N and 32N but not 33N,
-- so it is added here with the standard Nigeria shift to WGS84 (Clarke 1880, -92 -93 122).
-- Wrapped so a database that does not allow it simply skips it (the choice then stays off).
DO $$
BEGIN
  INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text)
  VALUES (926333, 'SABAGEO', 926333, '',
          '+proj=utm +zone=33 +ellps=clrk80 +towgs84=-92,-93,122,0,0,0,0 +units=m +no_defs')
  ON CONFLICT (srid) DO NOTHING;
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'Could not add Minna / UTM 33N (no permission). Everything else is fine.';
END $$;
