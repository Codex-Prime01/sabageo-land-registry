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

-- An early draft of this file (never on Neon) gave staff a role column. One admin level now.
ALTER TABLE staff DROP COLUMN IF EXISTS role;

-- Rate limits kept in the database, so they survive a restart and work on more than one server.
-- Optional: without this table the limits fall back to server memory.
CREATE TABLE IF NOT EXISTS rate_hits (
  id      BIGSERIAL PRIMARY KEY,
  bucket  TEXT NOT NULL,
  visitor TEXT NOT NULL,
  hit_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rate_hits_lookup_idx ON rate_hits (bucket, visitor, hit_at);
