"""
Postgres data-access layer for the CobbleStone extraction backfill/sync
(see db/schema.sql). `requests`/`files` each store the complete original
CobbleStone record in a `raw` JSONB column plus a handful of first-class
columns used only for server-side filtering/indexing. Reads return `raw`
untouched, so the dicts handed back are byte-for-byte identical in shape to
what CobbleStone's API returns today — run_discovery.py/run_pairing.py/
run_review.py's existing field-access code needs no changes, only their
input-loading branch does.

Every function takes an explicit connection — callers open one connection
per script run (see backfill.py) rather than each call managing its own.
"""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

import config

# (column, CobbleStone field name) — only fields actually queried/indexed
# server-side; everything else lives in `raw` only. See the plan's rationale:
# promoting a new field later is an ALTER TABLE + backfill from `raw`, never
# a re-extraction from the API.
_REQUEST_FIELDS = [
    ("request_id", "RequestID"),
    ("request_title", "RequestTitle"),
    ("status_id", "StatusID"),
    ("u_request_process_status", "u_RequestProcessStatus"),
    ("entry_date", "EntryDate"),
    ("date_updated", "DateUpdated"),
    ("u_request_type", "u_RequestType"),
    ("u_marmon_sector", "u_MarmonSector"),
    ("u_marmon_business_unit_geography", "u_MarmonBusinessUnitGeography"),
    ("u_law_firm_name", "u_LawFirmName"),
    ("u_handling_attorney_email", "u_HandlingAttorneyEmail"),
    ("u_handling_attorney", "u_HandlingAttorney"),
    ("u_business_unit", "u_BusinessUnit"),
    ("u_vendor_counterparty_name", "u_VendorCounterpartyName"),
    ("u_requestor", "u_Requestor"),
    ("request_amount", "RequestAmount"),
    ("vendor_id", "VendorID"),
    ("entered_by", "EnteredBy"),
    ("employee_contact_id", "EmployeeContactID"),
]

_FILE_FIELDS = [
    ("id", "ID"),
    ("file_name", "FileName"),
    ("file_type", "FileType"),
    ("file_size_bytes", "FileSizeBytes"),
    ("entry_date", "EntryDate"),
    ("text_extract", "TextExtract"),
    ("keywords", "Keywords"),
]

_TIMESTAMP_COLUMNS = {"entry_date", "date_updated"}


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=config.PG_HOST, port=config.PG_PORT, dbname=config.PG_DB,
        user=config.PG_USER, password=config.PG_PASSWORD,
    )


def _ts(value):
    return datetime.fromisoformat(value) if value else None


def _extract(record: dict, fields: list) -> tuple:
    columns, values = [], []
    for column, api_field in fields:
        value = record.get(api_field)
        columns.append(column)
        values.append(_ts(value) if column in _TIMESTAMP_COLUMNS else value)
    return columns, values


def upsert_request(conn: psycopg.Connection, request: dict) -> None:
    columns, values = _extract(request, _REQUEST_FIELDS)
    columns.append("raw")
    values.append(Jsonb(request))
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "request_id")
    conn.execute(
        f"INSERT INTO requests ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (request_id) DO UPDATE SET {updates}",
        values,
    )


def upsert_file(conn: psycopg.Connection, file: dict, request_id: int) -> None:
    columns, values = _extract(file, _FILE_FIELDS)
    columns += ["request_id", "is_deleted", "raw"]
    values += [request_id, bool(file.get("IsDeleted")), Jsonb(file)]
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")
    conn.execute(
        f"INSERT INTO files ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}",
        values,
    )


def get_requests(conn: psycopg.Connection, limit: int | None = None,
                  business_sector: str | None = None, active_only: bool = False,
                  request_type: str | None = None, geography: str | None = None) -> list:
    where, params = [], []
    if business_sector:
        where.append("u_marmon_sector = %s")
        params.append(business_sector)
    if request_type:
        where.append("u_request_type = %s")
        params.append(request_type)
    if geography:
        where.append("u_marmon_business_unit_geography = %s")
        params.append(geography)
    if active_only:
        terminal = list(config.PROCESS_STATUS_CONTRACT_EXISTS | config.PROCESS_STATUS_NO_CONTRACT)
        where.append("(u_request_process_status IS NULL OR NOT (u_request_process_status = ANY(%s)))")
        params.append(terminal)
    sql = "SELECT raw FROM requests"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY request_id"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def get_requests_ranked_by_file_count(conn: psycopg.Connection, limit: int,
                                       request_type: str | None = None,
                                       geography: str | None = None,
                                       min_files: int = 2) -> list:
    """
    Same filters as get_requests(), but orders by (non-deleted) file count
    descending instead of request_id ascending, and only considers requests
    with at least `min_files` files.

    A draft-vs-signed pair can only come from a request with 2+ files —
    plain get_requests()'s default "oldest request_id first" ordering picks
    up whatever single-file requests happen to be old, wasting most of a
    capped --limit on requests pairing.py will just report
    "insufficient_files" for. Ranking by file count first means a capped
    sample (e.g. --limit 250 for a first-pass playbook) is made of the
    requests actually likely to yield a real redline, not just the oldest.
    """
    where, params = [], []
    if request_type:
        where.append("r.u_request_type = %s")
        params.append(request_type)
    if geography:
        where.append("r.u_marmon_business_unit_geography = %s")
        params.append(geography)

    sql = """
        SELECT r.raw, f.file_count
        FROM requests r
        JOIN (
            SELECT request_id, count(*) AS file_count
            FROM files
            WHERE is_deleted IS NOT TRUE
            GROUP BY request_id
            HAVING count(*) >= %s
        ) f ON f.request_id = r.request_id
    """
    params_full = [min_files] + params
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY f.file_count DESC, r.request_id LIMIT %s"
    params_full.append(limit)
    rows = conn.execute(sql, params_full).fetchall()
    return [row[0] for row in rows]


def _apply_text_repair(raw: dict, repaired: str | None) -> dict:
    """CobbleStone's own TextExtract is empty for most files from ~2023
    onward (confirmed live, every file type) — repair_text_extraction.py
    recovers it separately into text_extract_repaired, which sync/backfill
    never touch (see schema.sql). Preferring it here means every existing
    caller (pairing.py, review_selection.py, classifier.py, ...) sees real
    text with zero changes on their end — they already just read
    f.get("TextExtract")."""
    if repaired:
        return {**raw, "TextExtract": repaired}
    return raw


def get_files_for_request(conn: psycopg.Connection, request_id: int) -> list:
    cur = conn.execute(
        "SELECT raw, text_extract_repaired FROM files WHERE request_id = %s ORDER BY id",
        (request_id,),
    )
    return [_apply_text_repair(raw, repaired) for raw, repaired in cur.fetchall()]


def get_files_needing_text_repair(conn: psycopg.Connection, min_chars: int = 200,
                                    limit: int | None = None) -> list:
    """Files where CobbleStone's own TextExtract is empty/thin AND we haven't
    already recovered it ourselves — the work list for
    repair_text_extraction.py. Naturally resumable: once a file gets a
    text_extract_repaired value, it stops matching this query."""
    sql = """
        SELECT id, request_id, file_name, file_type, file_size_bytes
        FROM files
        WHERE is_deleted IS NOT TRUE
          AND length(coalesce(text_extract, '')) < %s
          AND text_extract_repaired IS NULL
        ORDER BY request_id, id
    """
    params = [min_chars]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    cols = ["id", "request_id", "file_name", "file_type", "file_size_bytes"]
    return [dict(zip(cols, row)) for row in rows]


def save_text_repair(conn: psycopg.Connection, file_id: int, text: str, source: str) -> None:
    # Postgres TEXT rejects NUL bytes outright (psycopg.DataError) — seen live
    # from a malformed/mislabeled file leaking a raw byte through extraction.
    # Stripping here (not per-extractor) catches it regardless of which
    # extractor produced it.
    text = text.replace("\x00", "")
    conn.execute(
        "UPDATE files SET text_extract_repaired = %s, text_extract_repair_source = %s WHERE id = %s",
        (text, source, file_id),
    )


def get_request(conn: psycopg.Connection, request_id: int) -> dict | None:
    """Single-request lookup by id — for scripts working off an already-known
    request id list (e.g. a saved request_meta.json) rather than a fresh
    get_requests()-style scan."""
    row = conn.execute("SELECT raw FROM requests WHERE request_id = %s", (request_id,)).fetchone()
    return row[0] if row else None


# ── Tracked-changes structure scan (scan_tracked_changes.py) ─────────────────
# Same sync-safety design as the text-repair columns: these are OUR derived
# columns, absent from upsert_file's explicit column list, so a sync can
# never clobber a scan result. structure_scanned_at doubles as the
# "already done" marker, making the scanner naturally resumable.

def get_files_needing_structure_scan(conn: psycopg.Connection,
                                     request_type: str | None = None,
                                     geography: str | None = None,
                                     limit: int | None = None) -> list:
    """Unscanned docx-family files, most-recent request first — recency-first
    because Jeff's selection funnel wants the newest contracts, so partial
    scan progress is immediately useful."""
    sql = """
        SELECT f.id, f.request_id, f.file_name, f.file_type, f.file_size_bytes
        FROM files f
        JOIN requests r ON r.request_id = f.request_id
        WHERE f.is_deleted IS NOT TRUE
          AND lower(f.file_type) IN ('.docx', '.docm', '.dotx')
          AND f.structure_scanned_at IS NULL
    """
    params: list = []
    if request_type:
        sql += " AND r.u_request_type = %s"
        params.append(request_type)
    if geography:
        sql += " AND r.u_marmon_business_unit_geography = %s"
        params.append(geography)
    sql += " ORDER BY r.entry_date DESC NULLS LAST, f.id"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    cols = ["id", "request_id", "file_name", "file_type", "file_size_bytes"]
    return [dict(zip(cols, row)) for row in rows]


def _clean(text: str | None) -> str | None:
    """Postgres TEXT rejects NUL bytes outright (psycopg.DataError) — seen
    live from a malformed file leaking a raw byte through extraction."""
    return text.replace("\x00", "") if text else text


def save_structure_scan(conn: psycopg.Connection, file_id: int, parsed: dict,
                         note: str | None = None) -> None:
    """Persists a docx_redline.parse_docx_redline() result — including the
    base/proposed renderings and per-edit list for files that carry tracked
    changes, so no file ever needs downloading and re-parsing later (see
    schema.sql). A failed parse (ok=False) still stamps structure_scanned_at
    with has_tracked_changes NULL — 'we looked and couldn't tell' is a real,
    recorded outcome, distinct from FALSE ('we looked, there are none'), and
    either way the file leaves the work list."""
    if not parsed.get("ok"):
        conn.execute(
            """UPDATE files SET has_tracked_changes = NULL, structure_scan_note = %s,
               structure_scanned_at = now() WHERE id = %s""",
            (note or parsed.get("error"), file_id),
        )
        return

    has_tc = parsed["has_tracked_changes"]
    # Only redlines get the heavy columns: for a clean document base and
    # proposed text are identical to each other and to text_extract_repaired,
    # so storing them would be duplication for no gain.
    edits = [
        {"author": e["author"], "date": e["date"].isoformat() if e["date"] else None,
         "kind": e["kind"], "text": _clean(e["text"])}
        for e in parsed["edits"]
    ] if has_tc else None
    conn.execute(
        """UPDATE files SET has_tracked_changes = %s, tracked_change_count = %s,
           tracked_change_authors = %s, tracked_change_first_date = %s,
           tracked_change_last_date = %s, redline_base_text = %s,
           redline_proposed_text = %s, tracked_change_edits = %s,
           structure_scan_note = %s, structure_scanned_at = now()
           WHERE id = %s""",
        (has_tc, parsed["edit_count"], Jsonb(parsed["authors"]),
         parsed["first_date"], parsed["last_date"],
         _clean(parsed["base_text"]) if has_tc else None,
         _clean(parsed["proposed_text"]) if has_tc else None,
         Jsonb(edits) if edits is not None else None,
         note, file_id),
    )


def mark_structure_scan_skipped(conn: psycopg.Connection, file_id: int,
                                 note: str | None = None) -> None:
    """For files whose bytes couldn't be downloaded at all — stamped so they
    leave the work list rather than being re-attempted forever; re-scan by
    clearing structure_scanned_at if CobbleStone recovers."""
    conn.execute(
        "UPDATE files SET structure_scan_note = %s, structure_scanned_at = now() WHERE id = %s",
        (note, file_id),
    )


# ── NDA directionality classification (azure_nda_classifier.py) ─────────────
# Moved from JSON-only (--out) persistence into first-class columns per the
# 2026-08-31 decision: an LLM classification is expensive, reusable work and
# must never be silently repeated. Absent from upsert_request's column list
# → sync-safe, like everything else we derive.

def save_nda_classification(conn: psycopg.Connection, request_id: int, nda_type: str,
                             reasoning: str, source_file_id: int | None,
                             model: str | None = None) -> None:
    conn.execute(
        """UPDATE requests SET nda_type = %s, nda_type_reasoning = %s,
           nda_type_source_file_id = %s, nda_type_model = %s,
           nda_type_classified_at = now()
           WHERE request_id = %s""",
        (nda_type, reasoning, source_file_id, model, request_id),
    )


def get_nda_classifications(conn: psycopg.Connection) -> dict:
    """{request_id: {"nda_type", "reasoning"}} for every classified request —
    the check-before-you-classify read that keeps LLM work from repeating."""
    rows = conn.execute(
        "SELECT request_id, nda_type, nda_type_reasoning FROM requests WHERE nda_type IS NOT NULL"
    ).fetchall()
    return {r[0]: {"nda_type": r[1], "reasoning": r[2]} for r in rows}


def get_redline_funnel_requests(conn: psycopg.Connection, request_type: str = "NDA",
                                 geography: str = "U.S.") -> list:
    """Jeff's selection funnel, DB-side: requests of the given type/geography
    that have at least one tracked-changes docx, newest first, with their
    classification state — the input to the classify-until-target loop and
    to the funnel report."""
    rows = conn.execute(
        """
        SELECT r.request_id, r.request_title, r.entry_date, r.nda_type,
               COUNT(*) FILTER (WHERE f.has_tracked_changes) AS redline_docx_count
        FROM requests r
        JOIN files f ON f.request_id = r.request_id
        WHERE r.u_request_type = %s
          AND r.u_marmon_business_unit_geography = %s
          AND f.is_deleted IS NOT TRUE
        GROUP BY r.request_id, r.request_title, r.entry_date, r.nda_type
        HAVING COUNT(*) FILTER (WHERE f.has_tracked_changes) > 0
        ORDER BY r.entry_date DESC NULLS LAST
        """,
        (request_type, geography),
    ).fetchall()
    cols = ["request_id", "request_title", "entry_date", "nda_type", "redline_docx_count"]
    return [dict(zip(cols, row)) for row in rows]


# ── Clause tagging results ────────────────────────────────────────────────
# Per-request LLM output, committed as each request finishes. See
# db/schema.sql's clause_tagging_results comment for why this is not held in
# memory until the end of the run. Sync-immune: absent from upsert_request /
# upsert_file column lists, so a CobbleStone refresh never clears it.

def scrub_nulls(value):
    """Strips U+0000 out of every string in a nested JSON structure.

    Postgres text and jsonb cannot represent a NUL: the driver reports
    "unsupported Unicode escape sequence ... \\u0000 cannot be converted to
    text" and the whole statement fails. NULs arrive here from Word/PDF text
    extraction, so they are noise in the source document rather than content —
    dropping them loses nothing.

    This lives at the database boundary on purpose. One request out of 1,812
    carried a NUL, and it was enough to abort a transaction mid-run; every
    writer to these columns needs the same protection, not just the one that
    happened to hit it first.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [scrub_nulls(v) for v in value]
    if isinstance(value, dict):
        # Keys too: a NUL anywhere in the document breaks the statement, and
        # jsonb object keys are text like any other.
        return {scrub_nulls(k): scrub_nulls(v) for k, v in value.items()}
    return value


def save_clause_tagging(conn: psycopg.Connection, population_tag: str, model: str | None,
                         result: dict, chunk_signature: str | None = None) -> None:
    """Stores one request's finished tagging result. Called per request and
    committed immediately, so a crash costs only the in-flight requests."""
    conn.execute(
        """INSERT INTO clause_tagging_results
               (request_id, population_tag, model, chunk_signature, tagging_failed,
                verified_findings, low_or_noise_findings, verification_failed_count, tagged_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (request_id, population_tag) DO UPDATE SET
               model = EXCLUDED.model,
               chunk_signature = EXCLUDED.chunk_signature,
               tagging_failed = EXCLUDED.tagging_failed,
               verified_findings = EXCLUDED.verified_findings,
               low_or_noise_findings = EXCLUDED.low_or_noise_findings,
               verification_failed_count = EXCLUDED.verification_failed_count,
               tagged_at = now()""",
        (result["request_id"], population_tag, model, chunk_signature,
         bool(result.get("tagging_failed")),
         Jsonb(scrub_nulls(result.get("verified_findings") or [])),
         Jsonb(scrub_nulls(result.get("low_or_noise_findings") or [])),
         int(result.get("verification_failed_count") or 0)),
    )


def update_clause_tagging_findings(conn: psycopg.Connection, population_tag: str,
                                    request_id: int, verified_findings: list,
                                    low_or_noise_findings: list) -> None:
    """Replaces only the two findings columns for one request, leaving model,
    chunk_signature and tagged_at alone.

    Used by annotate_finding_sides.py so side attribution lands in Postgres and
    not only in a JSON file. Without this the database permanently held
    un-attributed findings, and anything re-exported from it silently lost every
    position_side — which is the whole point of the exercise."""
    conn.execute(
        """UPDATE clause_tagging_results
           SET verified_findings = %s, low_or_noise_findings = %s
           WHERE population_tag = %s AND request_id = %s""",
        (Jsonb(scrub_nulls(verified_findings)), Jsonb(scrub_nulls(low_or_noise_findings)),
         population_tag, request_id),
    )


def get_clause_tagging(conn: psycopg.Connection, population_tag: str) -> dict:
    """{request_id: result-dict} for a population — the read that makes a
    re-run resume instead of repeating work. Returns the same shape the tagger
    produces, plus chunk_signature so the caller can detect stale input."""
    rows = conn.execute(
        """SELECT request_id, chunk_signature, tagging_failed, verified_findings,
                  low_or_noise_findings, verification_failed_count, model, tagged_at
           FROM clause_tagging_results WHERE population_tag = %s""",
        (population_tag,),
    ).fetchall()
    return {
        r[0]: {
            "request_id": r[0],
            "chunk_signature": r[1],
            "tagging_failed": r[2],
            "verified_findings": r[3] or [],
            "low_or_noise_findings": r[4] or [],
            "verification_failed_count": r[5] or 0,
            "model": r[6],
            "tagged_at": r[7],
        }
        for r in rows
    }


def max_request_id(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(request_id), 0) FROM requests").fetchone()[0]


def get_sync_state(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        "SELECT last_incremental_watermark, last_run_at, last_run_status FROM sync_state WHERE id = 1"
    ).fetchone()
    return {"last_incremental_watermark": row[0], "last_run_at": row[1], "last_run_status": row[2]}


def update_sync_state(conn: psycopg.Connection, **fields) -> None:
    assignments = ", ".join(f"{k} = %s" for k in fields)
    conn.execute(f"UPDATE sync_state SET {assignments} WHERE id = 1", list(fields.values()))
