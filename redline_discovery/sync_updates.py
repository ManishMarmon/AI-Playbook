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

from datetime import datetime

import config
import db
from request_api import (
    get_bearer_token, fetch_all_requests, fetch_requests_updated_since, fetch_request_file_list,
)


def _upsert_request_and_files(conn, token, request: dict) -> int:
    request_id = request.get("RequestID")
    files = fetch_request_file_list(request_id, token)
    db.upsert_request(conn, request)
    for f in files:
        db.upsert_file(conn, f, request_id)
    conn.commit()
    return len(files)


def main():
    conn = db.get_connection()
    token = get_bearer_token()
    run_started_at = datetime.now()

    # Pass 1: brand-new requests.
    start_after_id = db.max_request_id(conn)
    new_requests = fetch_all_requests(token, start_after_id=start_after_id)
    print(f"New requests since RequestID {start_after_id}: {len(new_requests)}")
    for request in new_requests:
        _upsert_request_and_files(conn, token, request)

    # Pass 2: requests whose DateUpdated changed since the last sync run.
    # Skipped on the very first run — the backfill that preceded it already
    # has everything current as of then, nothing has "changed" yet.
    state = db.get_sync_state(conn)
    watermark = state["last_incremental_watermark"]
    if watermark:
        try:
            changed = fetch_requests_updated_since(token, since=watermark)
            print(f"Requests updated since {watermark}: {len(changed)}")
            for request in changed:
                _upsert_request_and_files(conn, token, request)
        except Exception as e:
            print(f"DateUpdated-based change detection failed ({e}); "
                  f"relying on the active-request file refresh below instead.")
    else:
        print("No prior sync watermark — skipping change detection this run (first sync after backfill).")

    # Pass 3: refresh file lists for still-active (non-terminal) requests.
    active_requests = db.get_requests(conn, active_only=True)
    print(f"Refreshing files for {len(active_requests)} active requests...")
    refreshed_files = 0
    for i, request in enumerate(active_requests, 1):
        request_id = request.get("RequestID")
        files = fetch_request_file_list(request_id, token)
        for f in files:
            db.upsert_file(conn, f, request_id)
        conn.commit()
        refreshed_files += len(files)
        if i % 25 == 0:
            print(f"  ...{i}/{len(active_requests)} active requests refreshed")

    db.update_sync_state(
        conn,
        last_incremental_watermark=run_started_at,
        last_run_at=run_started_at,
        last_run_status="success",
    )
    conn.commit()
    conn.close()

    print("=" * 50)
    print(f"New requests:           {len(new_requests)}")
    print(f"Active requests refreshed: {len(active_requests)} ({refreshed_files} files)")
    print("=" * 50)


if __name__ == "__main__":
    main()
