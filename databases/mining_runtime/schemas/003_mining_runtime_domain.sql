-- Mining Runtime Schema v1.2 - Add domain/channel to mining_runs
-- Incremental migration: safe to run on existing databases.

ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS domain TEXT;
ALTER TABLE mining_runs ADD COLUMN IF NOT EXISTS channel TEXT;

CREATE INDEX IF NOT EXISTS idx_mining_runs_domain
    ON mining_runs(domain);
