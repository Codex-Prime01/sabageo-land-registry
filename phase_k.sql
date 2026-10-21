-- SABAGeo Land Registry: Phase K (the Help chat learns from the questions people ask)
-- Safe to run on your existing database, and safe to run more than once. Nothing is deleted.
-- Optional: without these tables the Help chat still answers from its built-in answers,
-- it just can't save questions or use the answers admins add.

-- Answers written by admins on /admin/help. They are used next to the built-in answers.
CREATE TABLE IF NOT EXISTS help_answers (
  id         SERIAL PRIMARY KEY,
  question   TEXT NOT NULL,
  keywords   TEXT NOT NULL DEFAULT '',
  answer     TEXT NOT NULL,
  active     BOOLEAN NOT NULL DEFAULT TRUE,
  staff_id   INTEGER REFERENCES staff(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- One row per question asked in the Help chat (no names, tokens or coordinates).
-- answer_key is empty when the chat had no good answer: those show up for admins to answer.
-- feedback_key is a hash of the key the asker gets back, so only they can rate the answer.
CREATE TABLE IF NOT EXISTS help_log (
  id           BIGSERIAL PRIMARY KEY,
  question     TEXT NOT NULL,
  page         TEXT,
  answer_key   TEXT,
  score        REAL,
  helpful      BOOLEAN,
  feedback_key TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS help_log_time_idx ON help_log (created_at DESC);
