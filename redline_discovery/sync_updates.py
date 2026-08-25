"""
Ongoing incremental sync — keeps Postgres current after the one-time
backfill (backfill.py), without re-fetching all ~19,701 requests every time.

Three passes:
  1. Brand-new requests (RequestID cursor past what's already stored).
  2. Requests whose DateUpdated changed since the last sync run (metadata
     edits on requests we already have).
  3. File-list refresh for still-"active" requests (not yet in a terminal
     u_RequestProcessStatus) — the only ones realistically getting new
     files/redlines, so this is far cheaper than re-checking all 19,701
     requests' files forever.

Run manually for now (`python -u sync_updates.py`); scheduling this
periodically is a fast-follow, not part of this pass.
"""

import json
from datetime import datetime

import config
import db
from request_api import (
    get_bearer_token, fetch_all_requests, fetch_requests_updated_since, fetch_request_file_list,
)

# A full sync's Pass 3 alone can be ~11,000 requests — hours of wall time.
# get_bearer_token() without force_refresh caches internally and only makes a
# real network call when near expiry, so calling it fresh before every single
# per-request API call (never holding one token in a variable across a loop)
# is free — this is the exact fix backfill.py needed after a token expired
# mid-run and crashed it outright. See backfill.py's own comment.


def _upsert_request_and_files(conn, request: dict) -> int:
    request_id = request.get("RequestID")
    files = fetch_request_file_list(request_id, get_bearer_token())
    db.upsert_request(conn, request)
    for f in files:
        db.upsert_file(conn, f, request_id)
    conn.commit()
    return len(files)


def main():
    conn = db.get_connection()
    run_started_at = datetime.now()
    errors = []

    # Pass 1: brand-new requests.
    start_after_id = db.max_request_id(conn)
    new_requests = fetch_all_requests(get_bearer_token(), start_after_id=start_after_id)
    print(f"New requests since RequestID {start_after_id}: {len(new_requests)}")
    for request in new_requests:
        request_id = request.get("RequestID")
        try:
            _upsert_request_and_files(conn, request)
        except Exception as e:
            conn.rollback()
            print(f"  Pass 1: failed to sync new request {request_id}: {e}")
            errors.append({"pass": 1, "request_id": request_id, "error": str(e)})

    # Pass 2: requests whose DateUpdated changed since the last sync run.
    # Skipped on the very first run — the backfill that preceded it already
    # has everything current as of then, nothing has "changed" yet. Unlike
    # before, a failure here (the bulk fetch itself, or any individual
    # request) does NOT advance the watermark and does NOT report success —
    # advancing past a window that was never actually applied would silently
    # and permanently skip those changes, since the next run's Pass 2 starts
    # from wherever the watermark says, not from what was truly synced.
    state = db.get_sync_state(conn)
    watermark = state["last_incremental_watermark"]
    pass2_ok = True
    if watermark:
        try:
            changed = fetch_requests_updated_since(get_bearer_token(), since=watermark)
            print(f"Requests updated since {watermark}: {len(changed)}")
        except Exception as e:
            pass2_ok = False
            changed = []
            print(f"DateUpdated-based change detection failed ({e}); watermark will NOT advance "
                  f"this run, so this window is retried next time. Relying on the active-request "
                  f"file refresh below for files in the meantime.")
        for request in changed:
            request_id = request.get("RequestID")
            try:
                _upsert_request_and_files(conn, request)
            except Exception as e:
                conn.rollback()
                pass2_ok = False
                print(f"  Pass 2: failed to sync updated request {request_id}: {e}")
                errors.append({"pass": 2, "request_id": request_id, "error": str(e)})
    else:
        print("No prior sync watermark — skipping change detection this run (first sync after backfill).")

    # Pass 3: refresh file lists for still-active (non-terminal) requests.
    active_requests = db.get_requests(conn, active_only=True)
    print(f"Refreshing files for {len(active_requests)} active requests...")
    refreshed_files = 0
    for i, request in enumerate(active_requests, 1):
        request_id = request.get("RequestID")
        try:
            files = fetch_request_file_list(request_id, get_bearer_token())
            for f in files:
                db.upsert_file(conn, f, request_id)
            conn.commit()
            refreshed_files += len(files)
        except Exception as e:
            conn.rollback()
            print(f"  Pass 3: failed to refresh files for request {request_id}: {e}")
            errors.append({"pass": 3, "request_id": request_id, "error": str(e)})
        if i % 25 == 0:
            print(f"  ...{i}/{len(active_requests)} active requests refreshed")

    # Only move the watermark forward if Pass 2 (the pass the watermark
    # actually gates) fully succeeded or was legitimately skipped (first run).
    # A Pass 1/Pass 3 per-request failure doesn't block the watermark — those
    # requests just get retried by next run's Pass 1 cursor / Pass 3 active
    # scan on their own, no separate bookkeeping needed.
    new_watermark = run_started_at if pass2_ok else watermark
    status = "success" if (pass2_ok and not errors) else ("success_with_errors" if pass2_ok else "pass2_failed")

    db.update_sync_state(
        conn,
        last_incremental_watermark=new_watermark,
        last_run_at=run_started_at,
        last_run_status=status,
    )
    conn.commit()
    conn.close()

    if errors:
        errors_path = config.OUTPUT_DIR / "sync_errors.json"
        errors_path.write_text(json.dumps(errors, indent=2, default=str), encoding="utf-8")

    print("=" * 50)
    print(f"New requests:           {len(new_requests)}")
    print(f"Active requests refreshed: {len(active_requests)} ({refreshed_files} files)")
    print(f"Run status:             {status}")
    print(f"Errors:                 {len(errors)}" + (f" (see {config.OUTPUT_DIR / 'sync_errors.json'})" if errors else ""))
    print("=" * 50)


if __name__ == "__main__":
    main()
