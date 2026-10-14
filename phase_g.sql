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
