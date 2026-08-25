"""
File-pairing + diff extraction — v2 of the Redline Discovery Engine.

For each request: fetch its full record + files, pick the (original, redline)
pair, and diff them to get concrete edits with location/context — e.g. a
"Permitted Disclosure" clause edit or a Preamble deletion, per the playbook's
Phase 4 goal. Requests are tagged with their u_RequestProcessStatus category
(not dropped) so a human/dashboard can decide what to skip.

Usage:
    python run_pairing.py --limit 200
    python run_pairing.py --limit 100 --snapshot output/pipeline_snapshot.json
"""

import argparse
import json
import re
import shutil
from collections import Counter

import config
import db
from request_api import load_pipeline_snapshot
from pairing import pair_files
from diffing import diff_documents, MAX_EDITS


def _process_status_tag(status: str) -> str:
    if status in config.PROCESS_STATUS_CONTRACT_EXISTS:
        return "contract_already_exists"
    if status in config.PROCESS_STATUS_NO_CONTRACT:
        return "no_contract_expected"
    return "in_progress"


def _population_tag(request_type: str | None, geography: str | None) -> str:
    """Filesystem-safe tag identifying this run's population, so two runs for
    different contract types/jurisdictions never share (and therefore never
    clobber) the same diff_chunks/redline_diffs/pairing_summary output. This
    is the exact fix for the Equipment Leasing near-miss: an NDA pairing run
    would have unconditionally rmtree'd Equipment Leasing's still-in-flight
    diff_chunks/ if it hadn't been caught and manually backed up first.
    Falls back to "all" when no filter is given, matching a full-population
    run — there's nothing else at that path to collide with."""
    parts = [p for p in (request_type, geography) if p]
    if not parts:
        return "all"
    slug = re.sub(r"[^a-z0-9]+", "-", "_".join(parts).lower()).strip("-")
    return slug or "all"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--request-type", default=None,
                         help="Only scan requests with this u_RequestType (e.g. 'Real Estate')")
    parser.add_argument("--geography", default=None,
                         help="Only scan requests with this u_MarmonBusinessUnitGeography (e.g. 'U.S.')")
    parser.add_argument("--snapshot", default=None,
                         help="Path to a pipeline snapshot (see fetch_snapshot.py) to reuse "
                              "instead of reading from Postgres — for one-off testing against a "
                              "fixed export")
    parser.add_argument("--best", action="store_true",
                         help="Rank candidates by (non-deleted) file count descending instead of "
                              "oldest-request-id-first, so a capped --limit picks requests actually "
                              "likely to have a real draft-vs-signed pair rather than whichever old "
                              "single-file requests come first.")
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    tag = _population_tag(args.request_type, args.geography)
    print(f"Population tag for this run's outputs: '{tag}'")
    conn = db.get_connection()

    if args.snapshot:
        print(f"Loading requests + files from snapshot: {args.snapshot}")
        snapshot = load_pipeline_snapshot(args.snapshot)
        requests_ = snapshot["requests"][:args.limit] if args.limit else snapshot["requests"]
        files_by_request = snapshot["files_by_request"]
    elif args.best:
        print(f"Loading up to {args.limit} requests from Postgres, ranked by file count "
              f"(request_type={args.request_type!r}, geography={args.geography!r})...")
        requests_ = db.get_requests_ranked_by_file_count(
            conn, limit=args.limit, request_type=args.request_type, geography=args.geography)
        files_by_request = None
    else:
        print(f"Loading up to {args.limit} requests from Postgres "
              f"(request_type={args.request_type!r}, geography={args.geography!r})...")
        requests_ = db.get_requests(conn, limit=args.limit, request_type=args.request_type,
                                     geography=args.geography)
        files_by_request = None
    print(f"Requests scanned: {len(requests_)}")

    results = []
    paired_count = 0
    edit_count = 0

    for i, req in enumerate(requests_, 1):
        request_id = req.get("RequestID")
        files = (files_by_request[request_id] if files_by_request is not None
                 else db.get_files_for_request(conn, request_id))
        pairing = pair_files(req, files)

        record = {
            "request_id": request_id,
            "request_title": req.get("RequestTitle"),
            "requestor": req.get("u_Requestor"),
            "vendor": req.get("u_VendorCounterpartyName"),
            "process_status": req.get("u_RequestProcessStatus"),
            "process_status_tag": _process_status_tag(req.get("u_RequestProcessStatus")),
            "file_count": pairing["file_count"],
            "total_file_count": pairing["total_file_count"],
            "pairing_method": pairing["method"],
            "similarity": pairing["similarity"],
            "low_similarity_warning": pairing["low_similarity_warning"],
            "original_file": pairing["original"].get("FileName") if pairing["original"] else None,
            "redline_file": pairing["redline"].get("FileName") if pairing["redline"] else None,
            "final_executed_file": pairing["final_executed_file"],
            "edits": [],
            "edits_truncated": False,
            "total_edit_opcodes": 0,
        }

        if pairing["original"] and pairing["redline"]:
            diff_result = diff_documents(
                pairing["original"].get("TextExtract") or "",
                pairing["redline"].get("TextExtract") or "",
            )
            record["edits"] = diff_result["edits"]
            record["edits_truncated"] = diff_result["truncated"]
            record["total_edit_opcodes"] = diff_result["total_edit_opcodes"]
            if record["edits"]:
                paired_count += 1
                edit_count += len(record["edits"])

        results.append(record)

        if i % 25 == 0 or i == len(requests_):
            print(f"  ...{i}/{len(requests_)} requests processed, "
                  f"{paired_count} pairs diffed, {edit_count} edits found so far")

    conn.close()

    out_path = config.OUTPUT_DIR / f"redline_diffs__{tag}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    # Per-request chunk files for the Phase 5 clause-tagging workflow (one JSON
    # file per request with a non-empty diff, named "<request_id>.json") — this
    # is the "chunkDir" the workflow's README usage note already documents.
    # Rebuilt from scratch each run so a request that no longer pairs doesn't
    # leave a stale chunk behind — but namespaced by population tag, so
    # rebuilding THIS population's chunks can never touch another
    # population's still-in-flight chunk_dir (see _population_tag).
    chunk_dir = config.OUTPUT_DIR / f"diff_chunks__{tag}"
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True)
    for r in results:
        if r["edits"]:
            (chunk_dir / f"{r['request_id']}.json").write_text(
                json.dumps(r, indent=2, default=str), encoding="utf-8"
            )

    tag_counts = dict(Counter(r["process_status_tag"] for r in results))
    method_counts = dict(Counter(r["pairing_method"] for r in results))
    truncated_count = sum(1 for r in results if r["edits_truncated"])

    summary = {
        "requests_scanned": len(requests_),
        "confirmed_redlines": paired_count,
        "extraction_failures": method_counts.get("insufficient_files", 0),
        "total_edits_found": edit_count,
        "pairs_truncated_at_max_edits": truncated_count,
        "process_status_breakdown": tag_counts,
        "pairing_method_breakdown": method_counts,
    }
    summary_path = config.OUTPUT_DIR / f"pairing_summary__{tag}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"Requests Scanned:          {len(requests_)}")
    print(f"Requests with a pair diffed: {paired_count}")
    print(f"Total edits found:         {edit_count}")
    print(f"Pairs truncated at MAX_EDITS ({MAX_EDITS}): {truncated_count}")
    print("Process status breakdown:")
    for status_tag, n in tag_counts.items():
        print(f"  {status_tag}: {n}")
    print("=" * 50)
    print(f"Wrote {out_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {paired_count} diff chunks to {chunk_dir}")


if __name__ == "__main__":
    main()
