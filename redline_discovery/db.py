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


def get_files_for_request(conn: psycopg.Connection, request_id: int) -> list:
    cur = conn.execute("SELECT raw FROM files WHERE request_id = %s ORDER BY id", (request_id,))
    return [row[0] for row in cur.fetchall()]


def get_request(conn: psycopg.Connection, request_id: int) -> dict | None:
    """Single-request lookup by id — for scripts working off an already-known
    request id list (e.g. a saved request_meta.json) rather than a fresh
    get_requests()-style scan."""
    row = conn.execute("SELECT raw FROM requests WHERE request_id = %s", (request_id,)).fetchone()
    return row[0] if row else None


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
