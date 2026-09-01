"""
Writes provenance-tagged diff chunks for a chosen set of requests, ready for
azure_clause_tagging.py.

Each chunk is the same shape run_pairing.py produces, so the tagger consumes
them unchanged, PLUS the fields Jeff's 2026-08-31 guidance requires:
comparison_basis (preferred position vs agreed outcome), source_files with
their document roles, per-edit authorship, and sequence_confidence. See
provenance_diff.py for how the basis is chosen.

Deterministic and free — no network, no LLM. Everything comes from what
scan_tracked_changes.py and run_sequencing.py already stored.

Usage:
    # the selected subset from report_redline_funnel.py (normal path)
    python -u run_provenance_diff.py --subset-file output/nda_redline_funnel.json \
        --tag nda-usa-mutual

    # ad-hoc
    python run_provenance_diff.py --request-ids 20644,20604 --tag smoke
"""

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

import config
import db
import provenance
from provenance_diff import build_request_diff

_FILE_COLS = [
    "id", "file_name", "document_role", "sequence_confidence", "has_tracked_changes",
    "redline_base_text", "redline_proposed_text", "tracked_change_edits",
    "tracked_change_authors", "tracked_change_first_date", "text",
]


def _files_for(conn, request_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, file_name, document_role, sequence_confidence, has_tracked_changes,
                  redline_base_text, redline_proposed_text, tracked_change_edits,
                  tracked_change_authors, tracked_change_first_date,
                  coalesce(text_extract_repaired, text_extract) AS text
           FROM files WHERE request_id = %s AND is_deleted IS NOT TRUE ORDER BY id""",
        (request_id,),
    ).fetchall()
    return [dict(zip(_FILE_COLS, r)) for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset-file", default=None,
                         help="JSON from report_redline_funnel.py (reads subset_request_ids)")
    parser.add_argument("--request-ids", default=None, help="Comma-separated request ids")
    parser.add_argument("--tag", required=True,
                         help="Population tag — chunks land in output/diff_chunks__<tag>/ so "
                              "runs for different populations never clobber each other")
    args = parser.parse_args()

    if args.subset_file:
        payload = json.loads(Path(args.subset_file).read_text(encoding="utf-8"))
        request_ids = payload["subset_request_ids"]
    elif args.request_ids:
        request_ids = [int(x) for x in args.request_ids.split(",")]
    else:
        parser.error("give --subset-file or --request-ids")

    conn = db.get_connection()
    print(f"Building provenance-tagged diffs for {len(request_ids)} request(s)...")

    records = []
    basis_counts = Counter()
    for i, rid in enumerate(request_ids, 1):
        request = db.get_request(conn, rid)
        if not request:
            print(f"  request {rid} not found in Postgres — skipped")
            continue
        # nda_type lives in a first-class column, not in the raw API record
        row = conn.execute("SELECT nda_type FROM requests WHERE request_id = %s", (rid,)).fetchone()
        request = {**request, "nda_type": row[0] if row else None}
        rec = build_request_diff(_files_for(conn, rid), request)
        records.append(rec)
        basis_counts[rec["comparison_basis"] or "none"] += 1
        if i % 25 == 0 or i == len(request_ids):
            print(f"  ...{i}/{len(request_ids)} processed")
    conn.close()

    chunk_dir = config.OUTPUT_DIR / f"diff_chunks__{args.tag}"
    if chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True)
    written = 0
    for rec in records:
        if rec["edits"]:
            (chunk_dir / f"{rec['request_id']}.json").write_text(
                json.dumps(rec, indent=2, default=str), encoding="utf-8")
            written += 1

    summary_path = config.OUTPUT_DIR / f"provenance_diffs__{args.tag}.json"
    summary_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")

    total_edits = sum(len(r["edits"]) for r in records)
    preferred = sum(1 for r in records if provenance.is_preferred_position(r["comparison_basis"]))
    truncated = sum(1 for r in records if r["edits_truncated"])
    attributed = sum(1 for r in records for e in r["edits"] if e.get("authors") != ["unattributed"])

    print(f"\nWrote {written} chunk file(s) to {chunk_dir}")
    print(f"Full records: {summary_path}")
    print(f"\nComparison basis distribution:")
    for basis, n in basis_counts.most_common():
        print(f"  {basis:<26} {n:>4}   ({provenance.label(basis) if basis != 'none' else 'no basis'})")
    print(f"\nPreferred-position requests: {preferred}/{len(records)} "
          f"({100*preferred/len(records):.0f}%)" if records else "")
    print(f"Total edits: {total_edits}   attributed to a named author: {attributed} "
          f"({100*attributed/total_edits:.0f}%)" if total_edits else "")
    if truncated:
        print(f"WARNING: {truncated} request(s) hit the edit cap — their diffs are truncated")


if __name__ == "__main__":
    main()
