-- Run this in pgAdmin's Query Tool while connected to the "aiplaybook"
-- database created by setup.sql.
--
-- Every table keeps the complete original CobbleStone record in `raw` JSONB
-- (nothing is ever lost, even fields nothing uses today) plus first-class
-- columns for the fields the pipeline actually filters/sorts/joins on.
-- Promoting a new field later is `ALTER TABLE ... ADD COLUMN` + a backfill
-- from `raw` — never a re-extraction from the API.

CREATE TABLE IF NOT EXISTS requests (
    request_id                  INT PRIMARY KEY,
    request_title                TEXT,
    status_id                    TEXT,
    u_request_process_status     TEXT,
    entry_date                   TIMESTAMP,
    date_updated                 TIMESTAMP,
    u_request_type               TEXT,
    u_marmon_sector               TEXT,
    u_marmon_business_unit_geography TEXT,
    u_law_firm_name               TEXT,
    u_handling_attorney_email     TEXT,
    u_handling_attorney           INT,
    u_business_unit               TEXT,
    u_vendor_counterparty_name    TEXT,
    u_requestor                   TEXT,
    request_amount                NUMERIC,
    vendor_id                     INT,
    entered_by                    INT,
    employee_contact_id           INT,
    raw                          JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_marmon_sector ON requests (u_marmon_sector);
CREATE INDEX IF NOT EXISTS idx_requests_process_status ON requests (u_request_process_status);
CREATE INDEX IF NOT EXISTS idx_requests_date_updated ON requests (date_updated);

CREATE TABLE IF NOT EXISTS files (
    id             INT PRIMARY KEY,
    request_id     INT NOT NULL REFERENCES requests (request_id),
    file_name      TEXT,
    file_type      TEXT,
    file_size_bytes BIGINT,
    entry_date     TIMESTAMP,
    text_extract   TEXT,
    keywords       TEXT,
    is_deleted     BOOLEAN,
    raw            JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_request_id ON files (request_id);

-- Single-row table tracking the incremental-sync checkpoint. The backfill's
-- own resume point doesn't need a row here — it just resumes from
-- MAX(request_id) in `requests`.
CREATE TABLE IF NOT EXISTS sync_state (
    id                        INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_incremental_watermark TIMESTAMP,
    last_run_at                TIMESTAMP,
    last_run_status             TEXT
);

INSERT INTO sync_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
