"""
Computes and persists each request's document-sequence roles (original ->
first_redline -> intermediate_redline -> final) using document_sequence.py,
so downstream stages can ask "which file is this request's first redline?"
as a plain SQL question.

Free and deterministic: no LLM calls, no network — it reads the tracked-changes
scan results and text already stored in Postgres by scan_tracked_changes.py.
Safe to re-run any time (roles are recomputed and overwritten); run it after
any scan so newly-scanned files get sequenced.

Usage:
    python run_sequencing.py --request-type NDA --geography U.S.     # the NDA universe
    python run_sequencing.py --request-ids 20644,20643               # specific requests
    python run_sequencing.py                                          # everything scanned
"""

import argparse
import time
from collections import Counter

import db
from data_refresh_lock import DataRefreshLock
from document_sequence import sequence_documents

COMMIT_EVERY = 200


def _files_for_sequencing(conn, request_id: int) -> list[dict]:
    """CobbleStone-shaped file dicts (what document_sequence expects) plus the
    scan columns it uses as its strongest signal. base_text is included so
    cohesion is judged on the redline's own reconstructed text rather than a
    possibly-rotted TextExtract."""
    rows = conn.execute(
        """SELECT id, file_name, entry_date,
                  coalesce(text_extract_repaired, text_extract) AS text,
                  has_tracked_changes, tracked_change_count, tracked_change_authors,
                  tracked_change_first_date, redline_base_text
           FROM files
           WHERE request_id = %s AND is_deleted IS NOT TRUE
           ORDER BY id""",
        (request_id,),
    ).fetchall()
    return [
        {
            "ID": r[0], "FileName": r[1], "EntryDate": r[2], "TextExtract": r[3],
            "has_tracked_changes": r[4], "tracked_change_count": r[5],
            "tracked_change_authors": r[6], "tracked_change_first_date": r[7],
            "base_text": r[8],
        }
        for r in rows
    ]


def _target_request_ids(conn, args) -> list[int]:
    if args.request_ids:
        return [int(x) for x in args.request_ids.split(",")]
    sql = """
        SELECT DISTINCT r.request_id
        FROM requests r JOIN files f ON f.request_id = r.request_id
        WHERE f.structure_scanned_at IS NOT NULL
    """
    params: list = []
    if args.request_type:
        sql += " AND r.u_request_type = %s"
        params.append(args.request_type)
    if args.geography:
        sql += " AND r.u_marmon_business_unit_geography = %s"
        params.append(args.geography)
    sql += " ORDER BY r.request_id"
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-type", default=None)
    parser.add_argument("--geography", default=None)
    parser.add_argument("--request-ids", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    try:
        with DataRefreshLock():
            _run(args)
    except RuntimeError as e:
        print(e)


def _run(args):
    conn = db.get_connection()
    request_ids = _target_request_ids(conn, args)
    if args.limit:
        request_ids = request_ids[:args.limit]
    print(f"Sequencing documents for {len(request_ids)} request(s)...")

    role_counts = Counter()
    confidence_counts = Counter()
    redline_requests = 0
    start = time.time()

    for i, rid in enumerate(request_ids, 1):
        files = _files_for_sequencing(conn, rid)
        result = sequence_documents(files)
        if result["has_redline_evidence"]:
            redline_requests += 1
        confidence_counts[result["request_confidence"]] += 1
        for file_id, role in result["roles"].items():
            role_counts[role["role"]] += 1
            conn.execute(
                """UPDATE files SET document_role = %s, sequence_confidence = %s,
                   sequence_reasoning = %s, sequence_computed_at = now()
                   WHERE id = %s""",
                (role["role"], role["confidence"], role["reasoning"], file_id),
            )
        if i % COMMIT_EVERY == 0:
            conn.commit()
        if i % 500 == 0 or i == len(request_ids):
            print(f"  ...{i}/{len(request_ids)} requests sequenced ({time.time()-start:.0f}s)")

    conn.commit()
    print(f"\nRequests with redline evidence: {redline_requests}/{len(request_ids)}")
    print(f"Request confidence: {dict(confidence_counts)}")
    print(f"File roles assigned: {dict(role_counts)}")
    conn.close()


if __name__ == "__main__":
    main()
