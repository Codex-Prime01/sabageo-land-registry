-- SABAGeo: payments, receipts and client login codes
-- Safe to run on an EXISTING database (skips anything that is already there).
-- Times use TIMESTAMPTZ because main.py compares them with UTC-aware datetimes.

CREATE SEQUENCE IF NOT EXISTS receipt_seq;

-- People or companies who paid
CREATE TABLE IF NOT EXISTS clients (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  client_type TEXT NOT NULL CHECK (client_type IN ('individual', 'corporate')),
  email       TEXT,
  phone       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per payment. reference is UNIQUE so the same bank reference can't be recorded twice.
CREATE TABLE IF NOT EXISTS payments (
  id          SERIAL PRIMARY KEY,
  client_id   INTEGER NOT NULL REFERENCES clients(id),
  receipt_no  TEXT UNIQUE NOT NULL,
  verify_code TEXT NOT NULL,
  amount_ngn  NUMERIC(14, 2) NOT NULL,
  method      TEXT NOT NULL,
  reference   TEXT UNIQUE NOT NULL,
  status      TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'void')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Login codes handed to clients. Only the hash is stored, never the code itself.
CREATE TABLE IF NOT EXISTS login_codes (
  id            SERIAL PRIMARY KEY,
  payment_id    INTEGER NOT NULL REFERENCES payments(id),
  client_id     INTEGER NOT NULL REFERENCES clients(id),
  code_hash     TEXT UNIQUE NOT NULL,
  expires_at    TIMESTAMPTZ NOT NULL,
  plots_allowed INTEGER,                      -- NULL means no limit
  plots_used    INTEGER NOT NULL DEFAULT 0,
  revoked       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS login_codes_payment_idx ON login_codes (payment_id);

-- Logged-in client sessions (token hash only)
CREATE TABLE IF NOT EXISTS client_sessions (
  id         SERIAL PRIMARY KEY,
  token_hash TEXT UNIQUE NOT NULL,
  code_id    INTEGER NOT NULL REFERENCES login_codes(id),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
