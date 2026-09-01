"""
Scans docx-family files for Word tracked-changes markup and persists the
results to Postgres (files.has_tracked_changes + author/date/count columns
— see db/schema.sql), so "which contracts have a real redlined Word
document" becomes a cheap SQL question instead of a re-download.

This is the foundation of Jeff's 2026-08-31 selection funnel: US mutual
NDAs -> has tracked-changes Word redline -> 100-200 most recent. Work list
is ordered most-recent-request-first so partial progress is immediately
useful to that funnel, and every file is stamped structure_scanned_at when
processed (success, parse-failure, or download-failure alike) making
re-runs naturally resumable — the same design as repair_text_extraction.py.

Usage:
    python scan_tracked_changes.py --limit 30                          # smoke test
    python -u scan_tracked_changes.py --request-type NDA --geography U.S.   # the NDA universe
    python -u scan_tracked_changes.py                                  # full population (hours)
"""

import argparse
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import db
from data_refresh_lock import DataRefreshLock
from docx_redline import parse_docx_redline
from request_api import get_bearer_token, download_file
from structure_check import has_pdf_annotations

WORKERS = 10
COMMIT_EVERY = 100

_EMPTY_PARSE = {"ok": True, "has_tracked_changes": False, "edit_count": 0, "authors": {},
                "first_date": None, "last_date": None, "edits": [],
                "base_text": "", "proposed_text": ""}


def _scan_one(f: dict) -> tuple[int, str, dict | None, str | None]:
    """Returns (file_id, outcome, parsed|None, note|None). Fresh
    get_bearer_token() at point of use — never hold a token across calls (the
    401-storm lesson)."""
    raw = download_file(f["id"], get_bearer_token())
    if not raw:
        return f["id"], "download_failed", None, "file bytes could not be downloaded"

    # CobbleStone's FileType is not trustworthy: several files named
    # "...redline....docx" are actually PDFs (confirmed live — bytes begin
    # %PDF-1.7). Such a file definitively has no WORD tracked changes, so
    # record FALSE with the reason rather than an inconclusive NULL, and check
    # it for PDF markup annotations instead so the evidence isn't just lost.
    if raw[:4] == b"%PDF":
        found, count = has_pdf_annotations(raw)
        note = (f"labelled {f.get('file_type')} but the bytes are a PDF; "
                f"{count} PDF markup annotation(s) found" if found else
                f"labelled {f.get('file_type')} but the bytes are a PDF; no PDF markup annotations")
        return f["id"], "mislabeled_pdf", dict(_EMPTY_PARSE), note

    parsed = parse_docx_redline(raw)
    if not parsed["ok"]:
        return f["id"], "parse_failed", parsed, parsed.get("error")
    outcome = "has_tracked_changes" if parsed["has_tracked_changes"] else "no_tracked_changes"
    return f["id"], outcome, parsed, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Max files this run (smoke-test with 30 or less first)")
    parser.add_argument("--request-type", default=None,
                         help="Only files belonging to requests of this u_RequestType (e.g. NDA)")
    parser.add_argument("--geography", default=None,
                         help="Only files belonging to requests of this geography (e.g. U.S.)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()

    try:
        with DataRefreshLock():
            _run(args)
    except RuntimeError as e:
        print(e)


def _run(args):
    conn = db.get_connection()
    todo = db.get_files_needing_structure_scan(
        conn, request_type=args.request_type, geography=args.geography, limit=args.limit)
    scope = f"request_type={args.request_type or 'ALL'} geography={args.geography or 'ALL'}"
    print(f"{len(todo)} docx-family files need a structure scan ({scope}"
          f"{f', --limit {args.limit}' if args.limit else ''})")
    if not todo:
        print("Nothing to do.")
        return

    run_start = time.time()
    outcomes = Counter()
    since_commit = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_scan_one, f): f for f in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                file_id, outcome, parsed, note = fut.result()
            except Exception as e:
                print(f"  file {f['id']} ({f.get('file_name')}): unexpected error ({e}) — skipped")
                outcomes["error"] += 1
                continue

            outcomes[outcome] += 1
            if outcome == "download_failed":
                db.mark_structure_scan_skipped(conn, file_id, note)
            else:
                db.save_structure_scan(conn, file_id, parsed, note)
            since_commit += 1
            if since_commit >= COMMIT_EVERY:
                conn.commit()
                since_commit = 0

            if i % 200 == 0 or i == len(todo):
                elapsed = time.time() - run_start
                print(f"...{i}/{len(todo)} scanned ({elapsed/60:.1f} min) — {dict(outcomes)}")

    conn.commit()
    elapsed = time.time() - run_start
    print(f"\nDone in {elapsed/60:.1f} min: {dict(outcomes)}")


if __name__ == "__main__":
    main()
