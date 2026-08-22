"""
B2 (Golden Rules review) — builds per-request review candidates: which
playbook applies (if any, via review_selection.select_playbook) and which
file's text represents the contract's current state to check against that
playbook's rules (review_selection.select_review_text). Doesn't call an LLM
itself — see workflows/golden_rules_review_workflow.js for the actual rule
evaluation, run separately via the Workflow tool against this script's output.

Usage:
    python run_review.py --limit 100
    python run_review.py --limit 100 --snapshot output/pipeline_snapshot.json
"""

import argparse
import json
from pathlib import Path

import config
import db
from request_api import load_pipeline_snapshot
from pairing import pair_files
from review_selection import select_playbook, select_review_text, catalog_other_files

PLAYBOOKS_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "playbooks"


def _load_manifest_and_playbooks():
    manifest = json.loads((PLAYBOOKS_DIR / "manifest.json").read_text(encoding="utf-8"))
    playbooks = {
        entry["id"]: json.loads((PLAYBOOKS_DIR / entry["file"]).read_text(encoding="utf-8"))
        for entry in manifest
    }
    return manifest, playbooks


def _load_negotiation_history(request_id: int) -> list[dict]:
    # Optional context only (see B2 plan) — a request with no Phase 5 output at
    # all (never re-run, or genuinely never negotiated) just gets an empty list,
    # not an error; the full-text scan carries 100% of the detection weight either way.
    path = config.OUTPUT_DIR / "clause_findings.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = ("clause_name", "change_type", "spirit_before", "spirit_after", "significance")
    return [
        {k: f.get(k) for k in fields}
        for f in data.get("confirmed", [])
        if f.get("request_id") == request_id
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--snapshot", default=None,
                         help="Path to a pipeline snapshot (see fetch_snapshot.py) to reuse "
                              "instead of reading from Postgres — for one-off testing against a "
                              "fixed export")
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)
    candidates_dir = config.OUTPUT_DIR / "review_candidates"
    candidates_dir.mkdir(exist_ok=True)

    manifest, playbooks = _load_manifest_and_playbooks()
    conn = db.get_connection()

    if args.snapshot:
        print(f"Loading requests + files from snapshot: {args.snapshot}")
        snapshot = load_pipeline_snapshot(args.snapshot)
        requests_ = snapshot["requests"][:args.limit] if args.limit else snapshot["requests"]
        files_by_request = snapshot["files_by_request"]
    else:
        print(f"Loading up to {args.limit} requests from Postgres...")
        requests_ = db.get_requests(conn, limit=args.limit)
        files_by_request = None
    print(f"Requests scanned: {len(requests_)}")

    request_meta = {}
    rules_by_id = {}
    skipped = []
    written = 0

    for req in requests_:
        request_id = req.get("RequestID")
        files = (files_by_request[request_id] if files_by_request is not None
                 else db.get_files_for_request(conn, request_id))

        business_sector = req.get("u_MarmonSector")
        contract_type = req.get("u_RequestType")
        selection = select_playbook(business_sector, manifest)
        playbook_id = selection["playbook_id"]
        if not playbook_id:
            skipped.append({"request_id": request_id, "reason": selection["reason"],
                             "business_sector": business_sector, "contract_type": contract_type})
            continue

        pairing_result = pair_files(req, files)
        review_text = select_review_text(req, files, pairing_result)
        if not review_text["text"]:
            skipped.append({"request_id": request_id, "reason": "no_review_text_available",
                             "business_sector": business_sector, "contract_type": contract_type})
            continue

        other_files = catalog_other_files(files, review_text.get("file_id"))
        other_nontemplate_files = [f for f in other_files if not f["looks_like_template"]]

        candidate = {
            "request_id": request_id,
            "request_title": req.get("RequestTitle"),
            "party_a": req.get("u_BusinessUnit"),
            "party_b": req.get("u_VendorCounterpartyName"),
            "playbook_id": playbook_id,
            "contract_text": review_text["text"],
            "contract_text_source": review_text["source"],
            "contract_text_truncated": review_text.get("truncated", False),
            "negotiation_history": _load_negotiation_history(request_id),
            # Every attached file NOT reviewed, so this candidate never silently
            # implies full coverage of everything filed under the request — see
            # review_selection.catalog_other_files.
            "other_files": other_files,
        }
        (candidates_dir / f"{request_id}.json").write_text(
            json.dumps(candidate, indent=2, default=str), encoding="utf-8"
        )
        written += 1

        playbook_label = next(e["label"] for e in manifest if e["id"] == playbook_id)
        request_meta[request_id] = {
            "request_title": req.get("RequestTitle"),
            "party_a": req.get("u_BusinessUnit"),
            "party_b": req.get("u_VendorCounterpartyName"),
            "playbook_id": playbook_id,
            "playbook_label": playbook_label,
            "other_files_count": len(other_files),
            "other_nontemplate_files_count": len(other_nontemplate_files),
        }
        # Full rule dict, not just the LLM-facing subset — the workflow's
        # orchestrator needs title/category/priority/preferred_language/source_tag
        # for the post-scan join and verify-priority gating (see plan); it decides
        # which fields actually go into the LLM prompt itself, not this script.
        for rule in playbooks[playbook_id]:
            rules_by_id[rule["rule_id"]] = rule

    conn.close()

    skipped_path = config.OUTPUT_DIR / "review_skipped.json"
    skipped_path.write_text(json.dumps(skipped, indent=2, default=str), encoding="utf-8")

    manifest_out = {"requestIds": list(request_meta.keys()), "requestMeta": request_meta, "rulesById": rules_by_id}
    manifest_path = config.OUTPUT_DIR / "review_run_manifest.json"
    manifest_path.write_text(json.dumps(manifest_out, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"Requests scanned:      {len(requests_)}")
    print(f"In scope (candidates): {written}")
    print(f"Skipped:               {len(skipped)}")
    print("=" * 50)
    print(f"Wrote {written} candidate files to {candidates_dir}")
    print(f"Wrote {skipped_path}")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
