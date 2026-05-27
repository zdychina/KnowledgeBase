-- Asset Core incremental migrations — safe to run on existing databases.

ALTER TABLE asset_publish_releases ADD COLUMN IF NOT EXISTS domain  TEXT NOT NULL DEFAULT 'default';
ALTER TABLE asset_publish_releases ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'prod';