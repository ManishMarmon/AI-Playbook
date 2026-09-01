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
    raw                          JSONB NOT NULL,
    -- NDA directionality (mutual / one-way), derived by
    -- azure_nda_classifier.py. Not a CobbleStone field, so upsert_request's
    -- explicit column list never includes it — a sync can never clobber a
    -- classification, same reasoning as files.text_extract_repaired below.
    -- This replaces that script's earlier JSON-only (--out) persistence: a
    -- classification must never be silently repeated.
    nda_type                     TEXT,
    nda_type_reasoning           TEXT,
    nda_type_source_file_id      INT,
    nda_type_classified_at       TIMESTAMP,
    -- Which deployment produced this classification. Recorded because the
    -- pipeline's default (gpt-5.6-luna) was unavailable on 2026-08-31 with
    -- HTTP 429 capacity errors and directionality classification ran on
    -- gpt-5.6-terra instead — validated first at 100% agreement (25/25)
    -- against luna's existing answers on this exact task. Auditable per row
    -- rather than inferred from run dates.
    nda_type_model               TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_marmon_sector ON requests (u_marmon_sector);
CREATE INDEX IF NOT EXISTS idx_requests_process_status ON requests (u_request_process_status);
CREATE INDEX IF NOT EXISTS idx_requests_date_updated ON requests (date_updated);
CREATE INDEX IF NOT EXISTS idx_requests_nda_type ON requests (nda_type);

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
    raw            JSONB NOT NULL,
    -- CobbleStone's own TextExtract stopped being populated for most files
    -- starting ~2023 (near-100% empty by 2025-2026, confirmed live across
    -- every file type, not format-specific) — text_extract/raw are left
    -- exactly as CobbleStone returns them (upsert_file() always overwrites
    -- both from the live API response, so anything written here would get
    -- silently clobbered on the next sync of an in-progress request). These
    -- two columns hold text WE recovered ourselves (see
    -- repair_text_extraction.py) by downloading the raw file and extracting
    -- locally — sync/backfill never touch them, and get_files_for_request()
    -- prefers this over text_extract when present.
    text_extract_repaired      TEXT,
    text_extract_repair_source TEXT,
    -- Word tracked-changes structure scan (see docx_redline.py,
    -- scan_tracked_changes.py) — same never-clobbered-by-sync reasoning as
    -- text_extract_repaired above. structure_scanned_at doubling as the
    -- "already scanned" marker makes the scanner naturally resumable, the
    -- same shape as get_files_needing_text_repair()'s work-list query.
    has_tracked_changes        BOOLEAN,
    tracked_change_count       INT,
    tracked_change_authors     JSONB,      -- {"Jane Doe": 12, "John Smith": 4}
    tracked_change_first_date  TIMESTAMP,
    tracked_change_last_date   TIMESTAMP,
    structure_scanned_at       TIMESTAMP,
    -- The full parse output, not just its summary counts. A redline .docx
    -- contains BOTH negotiation states — base = all tracked changes
    -- rejected (what walked in), proposed = all accepted (what walked out) —
    -- so diffing base-vs-proposed on ONE file yields the
    -- initial-vs-first-redline "preferred position" comparison even when the
    -- clean initial document was never uploaded. Stored because downloading
    -- and re-parsing thousands of files a second time to get text we already
    -- had in hand would be pure waste; the whole point of the scan is that a
    -- file is fetched and parsed exactly once, ever. Only populated for
    -- files that actually carry tracked changes.
    redline_base_text          TEXT,
    redline_proposed_text      TEXT,
    tracked_change_edits       JSONB,      -- [{"author","date","kind","text"}, ...] — per-edit attribution
    -- Anomalies worth surfacing rather than burying, e.g. CobbleStone
    -- labelling a file .docx when its bytes are actually a PDF (confirmed
    -- live: several "...redline...docx" files begin with %PDF-1.7). Such a
    -- file definitively has no WORD tracked changes, so has_tracked_changes
    -- is FALSE rather than NULL, and this column records why plus any PDF
    -- markup annotations found instead.
    structure_scan_note        TEXT,
    -- Document-sequence role within this request's negotiation (see
    -- document_sequence.py) — computed from the structure scan plus dates
    -- and filename markers. Never touched by upsert_file for the same
    -- sync-safety reason as everything else in this block.
    document_role              TEXT,       -- 'original' | 'first_redline' | 'intermediate_redline' | 'final'
    sequence_confidence        TEXT,       -- 'high' | 'medium' | 'low'
    sequence_reasoning         TEXT,
    sequence_computed_at       TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_request_id ON files (request_id);
CREATE INDEX IF NOT EXISTS idx_files_has_tracked_changes ON files (has_tracked_changes) WHERE has_tracked_changes = TRUE;

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

-- Per-request clause-tagging results. Every row is one request's finished
-- two-stage (tag + adversarial verify) LLM output, committed the moment that
-- request completes.
--
-- This table exists because the tagger used to hold every result in memory and
-- write one JSON file at the very end: on 2026-08-31 a DNS blip 95 requests
-- into a 97-request run raised out of the retry loop and the entire run's LLM
-- work was lost. Expensive derived understanding must survive a crash and must
-- never be recomputed — so results land here per request, and a re-run skips
-- what is already stored.
--
-- population_tag namespaces runs (nda-usa-mutual, real-estate, ...) so
-- different populations never overwrite each other's results.
--
-- chunk_signature is a hash of the exact diff-chunk input that produced the
-- row. If the upstream diff is rebuilt and the input actually changed, the
-- stored result is stale and the request is re-tagged automatically rather
-- than a resume quietly serving an answer derived from superseded input.
CREATE TABLE IF NOT EXISTS clause_tagging_results (
    request_id                INT NOT NULL REFERENCES requests (request_id),
    population_tag            TEXT NOT NULL,
    model                     TEXT,
    chunk_signature           TEXT,
    tagging_failed            BOOLEAN NOT NULL DEFAULT FALSE,
    verified_findings         JSONB,      -- high/medium findings, each with its verification verdict
    low_or_noise_findings     JSONB,      -- kept: never verified, but counted and reportable
    verification_failed_count INT NOT NULL DEFAULT 0,
    tagged_at                 TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, population_tag)
);

CREATE INDEX IF NOT EXISTS idx_clause_tagging_population
    ON clause_tagging_results (population_tag);
