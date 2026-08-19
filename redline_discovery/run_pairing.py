"""
File-pairing + diff extraction — v2 of the Redline Discovery Engine.

For each request: fetch its full record + files, pick the (original, redline)
pair, and diff them to get concrete edits with location/context — e.g. a
"Permitted Disclosure" clause edit or a Preamble deletion, per the playbook's
Phase 4 goal. Requests are tagged with their u_RequestProcessStatus category
(not dropped) so a human/dashboard can decide what to skip.

Usage:
    python run_pairing.py --limit 200
"""

import argparse
import json
from collections import Counter

import config
from request_api import get_bearer_token, fetch_all_requests, fetch_request_file_list
from pairing import pair_files
from diffing import diff_documents


def _process_status_tag(status: str) -> str:
    if status in config.PROCESS_STATUS_CONTRACT_EXISTS:
        return "contract_already_exists"
    if status in config.PROCESS_STATUS_NO_CONTRACT:
        return "no_contract_expected"
    return "in_progress"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    token = get_bearer_token()

    print(f"Fetching up to {args.limit} requests...")
    requests_ = fetch_all_requests(token, limit=args.limit)
    print(f"Requests scanned: {len(requests_)}")

    results = []
    paired_count = 0
    edit_count = 0

    for i, req in enumerate(requests_, 1):
        request_id = req.get("RequestID")
        files = fetch_request_file_list(request_id, token)
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
        }

        if pairing["original"] and pairing["redline"]:
            edits = diff_documents(
                pairing["original"].get("TextExtract") or "",
                pairing["redline"].get("TextExtract") or "",
            )
            record["edits"] = edits
            if edits:
                paired_count += 1
                edit_count += len(edits)

        results.append(record)

        if i % 25 == 0 or i == len(requests_):
            print(f"  ...{i}/{len(requests_)} requests processed, "
                  f"{paired_count} pairs diffed, {edit_count} edits found so far")

    out_path = config.OUTPUT_DIR / "redline_diffs.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    tag_counts = dict(Counter(r["process_status_tag"] for r in results))
    method_counts = dict(Counter(r["pairing_method"] for r in results))

    summary = {
        "requests_scanned": len(requests_),
        "confirmed_redlines": paired_count,
        "extraction_failures": method_counts.get("insufficient_files", 0),
        "total_edits_found": edit_count,
        "process_status_breakdown": tag_counts,
        "pairing_method_breakdown": method_counts,
    }
    summary_path = config.OUTPUT_DIR / "pairing_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"Requests Scanned:          {len(requests_)}")
    print(f"Requests with a pair diffed: {paired_count}")
    print(f"Total edits found:         {edit_count}")
    print("Process status breakdown:")
    for tag, n in tag_counts.items():
        print(f"  {tag}: {n}")
    print("=" * 50)
    print(f"Wrote {out_path}")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
