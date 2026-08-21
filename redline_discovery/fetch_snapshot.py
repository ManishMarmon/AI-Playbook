"""
Fetches every CobbleStone request + its file list exactly once and writes a
snapshot JSON, so run_discovery.py and run_pairing.py can both read from it
instead of each independently re-fetching the same data (see H3 in
CONTEXT.md — running both scripts back-to-back used to double every API call).

Usage:
    python fetch_snapshot.py --limit 100
    python run_discovery.py --limit 100 --snapshot output/pipeline_snapshot.json
    python run_pairing.py --limit 100 --snapshot output/pipeline_snapshot.json

Both scripts still work standalone with no --snapshot flag (unchanged, fresh
fetch) — this is a shared-fetch optimization, not a hard dependency.
"""

import argparse

import config
from request_api import get_bearer_token, fetch_pipeline_data, save_pipeline_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", default=None,
                         help="Snapshot output path (default: output/pipeline_snapshot.json)")
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = args.out or (config.OUTPUT_DIR / "pipeline_snapshot.json")

    token = get_bearer_token()
    print(f"Fetching up to {args.limit} requests + file lists...")
    data = fetch_pipeline_data(token, limit=args.limit)
    save_pipeline_snapshot(data, out_path)

    total_files = sum(len(f) for f in data["files_by_request"].values())
    print(f"Requests: {len(data['requests'])}, files: {total_files}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
