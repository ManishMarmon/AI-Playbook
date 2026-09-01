"""
Repairs CobbleStone's broken TextExtract by downloading each affected file's
raw bytes and extracting text locally instead.

Live-confirmed root cause: CobbleStone's own text extraction has been broken
across EVERY file type (not format-specific) since ~2023 — 1-3% of files
empty in 2020-2022, 43% in 2023, 88% in 2024, 100%/99.6% in 2025/2026. This
silently and severely skews which requests the rest of the pipeline can even
see: pairing.py/review_selection.py require >=200 chars of text per file
(pairing.py's MIN_TEXT_CHARS) to do anything at all, so any sample selection
that favors "requests where pairing actually succeeds" (e.g.
get_requests_ranked_by_file_count) systematically pushes recent (2024-2026)
requests out of the sample even though the underlying documents are
completely intact — confirmed live, e.g. the shipped 121-request NDA sample
is 91% from 2020-2023 versus 58% of the true 3,012-request population
actually being from 2024-2026.

This writes recovered text to files.text_extract_repaired (see
db.save_text_repair), NEVER to text_extract/raw directly — those two columns
get silently overwritten back to CobbleStone's still-empty value the next
time sync_updates.py refreshes an in-progress request's files, so patching
them directly would be a repair that quietly un-repairs itself later.
db.get_files_for_request() already prefers text_extract_repaired when
present, so every existing script (pairing.py, review_selection.py,
classifier.py, ...) sees the recovered text with zero changes on their end.

Coverage (see document_extraction.py / msg_extraction.py): .pdf, .docx and
its zip/XML siblings (.docm/.dotx), .xlsx and its sibling (.xlsm), .rtf,
.msg, .eml — roughly 94% of the files that need repair, live-counted. NOT
covered, by real remaining volume: .doc (legacy binary OLE format, not
zip/XML — needs a different approach entirely), .xls (legacy binary Excel),
.zip (would need to unzip and recurse), .jpg/.png (would need OCR, which
nothing in this pipeline does), .p7m (S/MIME signed container). These are
logged to --unsupported-out rather than silently skipped, so the residual
gap is a known, visible number, not an invisible one.

Usage:
    python repair_text_extraction.py --limit 50          # smoke test
    python -u repair_text_extraction.py                  # full run, all types, no limit
"""

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import db
from data_refresh_lock import DataRefreshLock
from document_extraction import extract_document_text
from msg_extraction import extract_email_text
from request_api import get_bearer_token, download_file

WORKERS = 10
DOCUMENT_TYPES = {".pdf", ".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".rtf"}
EMAIL_TYPES = {".msg", ".eml"}
COMMIT_EVERY = 100


def _repair_one(f: dict) -> tuple[int, str, str]:
    """Returns (file_id, outcome, text). outcome is one of:
    'recovered', 'empty_after_extraction', 'download_failed'.

    Calls get_bearer_token() fresh rather than taking a token param — this
    run can take many hours (CobbleStone's API has proven slow/unreliable at
    the full 35,623-file scale), and get_bearer_token() already caches and
    auto-refreshes internally. A token resolved once upfront and threaded
    through every worker for the run's whole lifetime goes stale mid-run and
    every download starts failing with 401 — the exact bug backfill.py hit
    and fixed before (see sync_updates.py's comment on the same fix)."""
    file_type = (f.get("file_type") or "").lower()
    raw = download_file(f["id"], get_bearer_token())
    if not raw:
        return f["id"], "download_failed", ""

    if file_type in DOCUMENT_TYPES:
        text = extract_document_text(raw, file_type)
    else:
        text = extract_email_text(raw, file_type)

    return f["id"], ("recovered" if text else "empty_after_extraction"), text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Max files to process this run (default: all that need repair). "
                              "Safe to re-run repeatedly to chunk a huge backlog — already-repaired "
                              "files stop matching the work-list query.")
    parser.add_argument("--min-chars", type=int, default=200,
                         help="A file's existing text_extract shorter than this is considered "
                              "'needs repair' (matches pairing.py's MIN_TEXT_CHARS convention)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--unsupported-out", default="output/text_repair_unsupported.json",
                         help="Where to log files whose type isn't handled at all (never attempted) "
                              "— the known, visible residual gap (.doc/.xls/.zip/.jpg/.png/.p7m/...)")
    args = parser.parse_args()

    try:
        with DataRefreshLock():
            _run(args)
    except RuntimeError as e:
        print(e)


def _run(args):
    conn = db.get_connection()
    candidates = db.get_files_needing_text_repair(conn, min_chars=args.min_chars, limit=None)
    print(f"{len(candidates)} files currently need text repair (text_extract < {args.min_chars} chars, "
          f"not yet repaired)")

    supported_types = DOCUMENT_TYPES | EMAIL_TYPES
    todo = [f for f in candidates if (f.get("file_type") or "").lower() in supported_types]
    unsupported = [f for f in candidates if (f.get("file_type") or "").lower() not in supported_types]

    by_unsupported_type = Counter((f.get("file_type") or "(none)").lower() for f in unsupported)
    print(f"{len(todo)} have a supported type; {len(unsupported)} do not "
          f"({dict(by_unsupported_type.most_common())})")
    Path(args.unsupported_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.unsupported_out).write_text(json.dumps(unsupported, indent=2), encoding="utf-8")

    if args.limit:
        todo = todo[:args.limit]
        print(f"Processing this run's slice: {len(todo)} files (--limit {args.limit})")

    if not todo:
        print("Nothing to do.")
        return

    run_start = time.time()
    outcomes = Counter()
    since_commit = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_repair_one, f): f for f in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                file_id, outcome, text = fut.result()
            except Exception as e:
                print(f"  file {f['id']} ({f.get('file_name')}): unexpected error ({e}) — skipped")
                outcomes["error"] += 1
                continue

            outcomes[outcome] += 1
            if outcome in ("recovered", "empty_after_extraction"):
                db.save_text_repair(conn, file_id, text, source=(f.get("file_type") or "").lower())
                since_commit += 1
                if since_commit >= COMMIT_EVERY:
                    conn.commit()
                    since_commit = 0

            if i % 200 == 0 or i == len(todo):
                elapsed = time.time() - run_start
                print(f"...{i}/{len(todo)} processed ({elapsed/60:.1f} min) — {dict(outcomes)}")

    conn.commit()
    elapsed = time.time() - run_start
    print(f"\nDone in {elapsed/60:.1f} min: {dict(outcomes)}")
    print(f"Unsupported-type files logged to {args.unsupported_out} ({len(unsupported)} files, never attempted)")


if __name__ == "__main__":
    main()
