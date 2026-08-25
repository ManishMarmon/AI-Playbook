"""
Builds the requestMeta lookup that clause_tagging_workflow.js's args expects
(request_title/party_a/party_b per request id), for whatever request ids
run_pairing.py wrote a diff chunk for.

This existed only as an ad-hoc, unsaved step in earlier synthesis runs (Real
Estate) — pulled out into a real script so every future contract-type/
jurisdiction playbook goes through the same reproducible pipeline end to end,
not a one-off command typed by hand.

Usage:
    python build_request_meta.py --chunk-dir output/diff_chunks__equipment-leasing-u-s \
        --out output/equipment_leasing_request_meta.json
"""

import argparse
import json
from pathlib import Path

import db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-dir", required=True,
                         help="Directory of per-request diff JSON files written by run_pairing.py "
                              "(filenames are '<request_id>.json') — defines which ids to look up")
    parser.add_argument("--out", required=True, help="Path to write the requestMeta JSON to")
    args = parser.parse_args()

    request_ids = sorted(int(p.stem) for p in Path(args.chunk_dir).glob("*.json"))

    conn = db.get_connection()
    by_id = {r["RequestID"]: r for r in db.get_requests(conn)}
    conn.close()

    meta = {}
    missing = []
    for rid in request_ids:
        r = by_id.get(rid)
        if not r:
            missing.append(rid)
            continue
        meta[str(rid)] = {
            "request_title": r.get("RequestTitle"),
            "party_a": r.get("u_BusinessUnit"),
            "party_b": r.get("u_VendorCounterpartyName"),
            # "vendor" is the field name clause_tagging_workflow.js's stamp()
            # (and azure_clause_tagging.py's port of it) actually reads onto
            # every finding — same underlying value as party_b, kept as an
            # explicit alias so this script's output works with both.
            "vendor": r.get("u_VendorCounterpartyName"),
        }

    if missing:
        print(f"WARNING: {len(missing)} request id(s) in {args.chunk_dir} not found in Postgres: {missing}")

    out_path = Path(args.out)
    out_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {len(meta)} of {len(request_ids)} request ids to {out_path}")


if __name__ == "__main__":
    main()
