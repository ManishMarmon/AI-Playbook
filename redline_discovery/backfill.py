"""
One-time, checkpointed, resumable full extraction of every CobbleStone
request + file list into Postgres (see db/schema.sql).

Resume is just "continue from what's already in the table" — no resume flag,
no separate checkpoint state. Each request is committed immediately after its
files are upserted, so a crash/interruption loses at most one in-flight
request; killing and re-running this script is always safe (upserts are
idempotent).

Usage:
    python -u backfill.py               # full run, all requests
    python -u backfill.py --limit 50    # smoke test
"""

import argparse
import json
import logging
import time

import config
import db
from data_refresh_lock import DataRefreshLock
from request_api import get_bearer_token, iter_request_pages, fetch_request_file_list

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# A full run takes hours — long enough for the OAuth token to expire mid-run
# (this killed an earlier run outright: get_bearer_token() was called once at
# startup and the resulting string held in a variable forever, so a 401 after
# the token's TTL propagated up as an uncaught HTTPError and crashed the whole
# process). get_bearer_token() already caches internally and only makes a real
# network call when near expiry, so calling it fresh before every use is free
# — never hold onto a token across more than one API call.
_MAX_PAGE_RETRIES = 5
_RETRY_BACKOFF_SECONDS = 10


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="Stop after this many new requests (default: no limit — full backfill)")
    args = parser.parse_args()

    try:
        with DataRefreshLock():
            _run(args)
    except RuntimeError as e:
        print(e)


def _run(args):
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    errors_path = config.OUTPUT_DIR / "backfill_errors.json"

    conn = db.get_connection()

    processed = 0
    file_count = 0
    errors = []

    # Outer retry loop: if listing a page itself fails (expired token, transient
    # network error — anything not already caught by the per-request try/except
    # below), don't let it kill an hours-long run. Recompute the resume point
    # from the DB (the only state that matters) and start a fresh page iterator
    # from there, same as a full process restart would do.
    page_retries = 0
    while True:
        start_after_id = db.max_request_id(conn)
        if args.limit is not None and processed >= args.limit:
            break
        remaining = None if args.limit is None else args.limit - processed
        print(f"Resuming backfill after RequestID {start_after_id}...")
        try:
            for page in iter_request_pages(get_bearer_token(), start_after_id=start_after_id, limit=remaining):
                page_retries = 0  # a page succeeded — reset the retry budget
                for request in page:
                    request_id = request.get("RequestID")
                    try:
                        token = get_bearer_token()
                        files = fetch_request_file_list(request_id, token)
                        db.upsert_request(conn, request)
                        for f in files:
                            db.upsert_file(conn, f, request_id)
                        conn.commit()
                        file_count += len(files)
                    except Exception as e:
                        conn.rollback()
                        logger.warning(f"Failed to backfill request {request_id}: {e}")
                        errors.append({"request_id": request_id, "error": str(e)})

                    processed += 1
                    if processed % 25 == 0:
                        print(f"  ...{processed} requests processed, {file_count} files so far")
            break  # iter_request_pages exhausted normally — full backfill done
        except Exception as e:
            page_retries += 1
            if page_retries > _MAX_PAGE_RETRIES:
                logger.error(f"Giving up after {_MAX_PAGE_RETRIES} consecutive page failures: {e}")
                raise
            logger.warning(f"Page listing failed ({e}); refreshing token and resuming "
                            f"from RequestID {db.max_request_id(conn)} (retry {page_retries}/{_MAX_PAGE_RETRIES})")
            time.sleep(_RETRY_BACKOFF_SECONDS)

    conn.close()

    if errors:
        errors_path.write_text(json.dumps(errors, indent=2), encoding="utf-8")

    print("=" * 50)
    print(f"Requests processed: {processed}")
    print(f"Files upserted:     {file_count}")
    print(f"Failures:           {len(errors)}" + (f" (see {errors_path})" if errors else ""))
    print("=" * 50)


if __name__ == "__main__":
    main()
