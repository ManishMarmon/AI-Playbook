"""
Annotates a clause-findings file with WHICH SIDE made each finding's edits —
Marmon(-subsidiary) or the counterparty — using author_attribution.py.

Runs as a separate step between tagging and synthesis, deliberately: the
author names are already on every finding (stamped by azure_clause_tagging.py
from the tracked-changes markup), so working out the side needs no LLM call
and no re-tagging. Re-runnable and idempotent.

Why this matters (Jeff, 2026-08-31): comparing only initial and final versions
made it hard to tell which party introduced a change. Tracked changes record
the author per edit, so for redlined documents that ambiguity is resolvable —
and a rule built from Marmon's own edits is a genuine preferred position,
whereas one built from the counterparty's edits is what they pushed back with.

Usage:
    python annotate_finding_sides.py --findings output/nda_mutual_clause_findings.json
    python annotate_finding_sides.py --findings <in> --out <out>   # keep the original
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import author_attribution as aa
import db
import provenance


def _findings_lists(payload):
    """Yields (list_name, list) for every findings list in the file, so both
    confirmed and flagged/low-noise findings get annotated."""
    result = payload.get("result", payload)
    for key in ("confirmed", "flagged", "low_or_noise", "lowOrNoise"):
        value = result.get(key)
        if isinstance(value, list):
            yield key, value


def annotate_one(f: dict, request: dict, roster) -> str:
    """Annotates a single finding in place and returns the side it was given.

    Extracted so the SAME logic serves both the JSON file and the Postgres rows.
    It previously existed only inline in the file loop, which meant the database
    kept the un-attributed findings forever: anything later exported from it —
    including the dashboard's own data file — silently lost every position_side,
    the exact attribution this stage exists to produce."""
    grouped = aa.group_authors_by_side(f.get("edit_authors") or [], request, roster)
    f["edit_author_sides"] = {k: v for k, v in grouped.items() if v}
    f["author_side_summary"] = aa.summarize_sides(grouped)

    # Whose position this finding represents. Tracked-change authorship first;
    # the source file's NAME only as a tie-breaker when the authors can't be
    # placed (it caught request 20597, whose "LP REDLINE" is the counterparty's
    # markup of our draft — labelling that a Marmon preferred position would
    # invert its meaning).
    if grouped[aa.MARMON] and not grouped[aa.COUNTERPARTY]:
        side = provenance.SIDE_MARMON
    elif grouped[aa.COUNTERPARTY] and not grouped[aa.MARMON]:
        side = provenance.SIDE_COUNTERPARTY
    elif grouped[aa.MARMON] and grouped[aa.COUNTERPARTY]:
        side = provenance.SIDE_UNKNOWN     # both sides edited — don't claim either
    else:
        source_files = f.get("source_files") or []
        first_name = source_files[0].get("file_name") if source_files else None
        side = aa.side_from_filename(first_name, request)

    f["position_side"] = side
    f["position_label"] = provenance.position_label(f.get("comparison_basis"), side)
    return side


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True)
    parser.add_argument("--out", default=None, help="Default: overwrite --findings in place")
    parser.add_argument("--population-tag", default=None,
                         help="Also write the annotations back into Postgres for this "
                              "population, so the database holds attributed findings and "
                              "anything re-exported from it keeps them")
    args = parser.parse_args()

    in_path = Path(args.findings)
    payload = json.loads(in_path.read_text(encoding="utf-8"))

    conn = db.get_connection()
    # Roster is built from the WHOLE redline population, not just this
    # findings file: an attorney whose name matches the handling-attorney
    # field on any request is then recognisable on requests where that field
    # happens to be blank.
    roster_rows = conn.execute(
        """SELECT r.raw, f.tracked_change_authors
           FROM requests r JOIN files f ON f.request_id = r.request_id
           WHERE f.has_tracked_changes AND f.tracked_change_authors IS NOT NULL"""
    ).fetchall()
    roster = aa.build_marmon_roster([(raw, list(authors or {})) for raw, authors in roster_rows])
    print(f"Marmon-side roster: {len(roster)} attorney name(s) confirmed across "
          f"{len(roster_rows)} redline file(s)")

    request_ids = {f.get("request_id") for _, lst in _findings_lists(payload) for f in lst}
    request_ids.discard(None)
    requests = {rid: db.get_request(conn, rid) or {} for rid in request_ids}

    summary_counts = Counter()
    position_counts = Counter()
    annotated = 0
    for _, findings in _findings_lists(payload):
        for f in findings:
            request = requests.get(f.get("request_id")) or {}
            annotate_one(f, request, roster)
            position_counts[f["position_label"]] += 1
            summary_counts[f["author_side_summary"]] += 1
            annotated += 1

    out_path = Path(args.out) if args.out else in_path
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Annotated {annotated} finding(s) -> {out_path}")
    for summary, n in summary_counts.most_common():
        print(f"  {n:>5}  {summary}")
    print("  position label (what each finding actually represents):")
    for label_text, n in position_counts.most_common():
        print(f"  {n:>5}  {label_text}")

    # Persist to Postgres as well, so the database is not left holding
    # un-attributed findings. Applied to the stored rows directly with the same
    # deterministic function rather than matching file findings back to rows —
    # same inputs, same outputs, nothing to mis-pair. Low/noise findings are
    # annotated too: they live only in the database, so this is the only place
    # they can ever get a side.
    if args.population_tag:
        stored = db.get_clause_tagging(conn, args.population_tag)
        db_annotated = 0
        for rid, row in stored.items():
            request = requests.get(rid) or db.get_request(conn, rid) or {}
            for f in row["verified_findings"]:
                annotate_one(f, request, roster)
                db_annotated += 1
            for f in row["low_or_noise_findings"]:
                annotate_one(f, request, roster)
                db_annotated += 1
            db.update_clause_tagging_findings(conn, args.population_tag, rid,
                                               row["verified_findings"],
                                               row["low_or_noise_findings"])
        conn.commit()
        print(f"  persisted sides for {db_annotated} finding(s) across {len(stored)} "
              f"request(s) in Postgres (population '{args.population_tag}')")

    conn.close()


if __name__ == "__main__":
    main()
