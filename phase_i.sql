-- SABAGeo Land Registry: Phase I (one Individual code = one plot)
-- Safe to run on your existing database, and safe to run more than once. Nothing is deleted.
-- Run it on Neon too, before deploying the code. Without it the site still works, but
-- Individual codes are not locked to one plot.

-- The plot a single-plot login code is locked to: set the first time the code checks a plot.
-- Stored as WGS84 text (the same form as the ledger), so it can be compared with later checks.
ALTER TABLE login_codes ADD COLUMN IF NOT EXISTS bound_wkt TEXT;
ALTER TABLE login_codes ADD COLUMN IF NOT EXISTS bound_at  TIMESTAMPTZ;
