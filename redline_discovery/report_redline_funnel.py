"""
Reports Jeff's selection funnel with real counts, from Postgres only — free,
instant, no network, no LLM.

The funnel (Jeff, 2026-08-31): the ~3,000 US NDA records don't all need
analyzing. Narrow to records that have a Word-document redline, then to the
most recent 100-200, to produce a representative output for review.

This is the evidence for the plan's Phase 0.3 gate ("review these numbers
before spending anything on LLM stages") and the numbers that go into the
methodology page of Monique's playbook, so it prints the population at every
stage rather than only the final subset.

Usage:
    python report_redline_funnel.py
    python report_redline_funnel.py --request-type NDA --geography U.S. --top 150 \
        --out output/nda_redline_funnel.json
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-type", default="NDA")
    parser.add_argument("--geography", default="U.S.")
    parser.add_argument("--top", type=int, default=150,
                         help="Subset size to characterize (Jeff's original range: 100-200)")
    parser.add_argument("--all-mutual", action="store_true",
                         help="Take EVERY classified-mutual request rather than the most recent "
                              "--top of them. Use when the playbook should cover the whole "
                              "population instead of a recent sample.")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    conn = db.get_connection()
    rt, geo = args.request_type, args.geography

    total = conn.execute(
        """SELECT COUNT(*) FROM requests
           WHERE u_request_type = %s AND u_marmon_business_unit_geography = %s""",
        (rt, geo)).fetchone()[0]

    with_docx = conn.execute(
        """SELECT COUNT(DISTINCT r.request_id) FROM requests r JOIN files f ON f.request_id = r.request_id
           WHERE r.u_request_type = %s AND r.u_marmon_business_unit_geography = %s
             AND f.is_deleted IS NOT TRUE AND lower(f.file_type) IN ('.docx','.docm','.dotx')""",
        (rt, geo)).fetchone()[0]

    scanned = conn.execute(
        """SELECT COUNT(DISTINCT r.request_id) FROM requests r JOIN files f ON f.request_id = r.request_id
           WHERE r.u_request_type = %s AND r.u_marmon_business_unit_geography = %s
             AND f.structure_scanned_at IS NOT NULL""",
        (rt, geo)).fetchone()[0]

    unscanned_files = conn.execute(
        """SELECT COUNT(*) FROM requests r JOIN files f ON f.request_id = r.request_id
           WHERE r.u_request_type = %s AND r.u_marmon_business_unit_geography = %s
             AND f.is_deleted IS NOT TRUE AND lower(f.file_type) IN ('.docx','.docm','.dotx')
             AND f.structure_scanned_at IS NULL""",
        (rt, geo)).fetchone()[0]

    funnel = db.get_redline_funnel_requests(conn, request_type=rt, geography=geo)
    mutual = [r for r in funnel if r["nda_type"] == "Mutual"]
    unclassified = [r for r in funnel if not r["nda_type"]]
    # Whole population or a recent slice. Recorded in scope (below) either way,
    # so the methodology page states which one the playbook actually used
    # instead of leaving a reader to infer it from the count.
    subset = mutual if args.all_mutual else mutual[:args.top]

    def year_hist(rows):
        return dict(sorted(Counter(
            r["entry_date"].year if r["entry_date"] else None for r in rows).items(),
            key=lambda kv: (kv[0] is None, kv[0])))

    print(f"=== {rt} / {geo} redline funnel ===")
    print(f"1. Total {rt} requests in {geo}:                {total:>6}")
    print(f"2. ...with at least one Word (.docx) file:      {with_docx:>6}")
    print(f"3. ...structure-scanned so far:                 {scanned:>6}"
          f"   ({unscanned_files} .docx files still unscanned)")
    print(f"4. ...with a TRACKED-CHANGES Word redline:      {len(funnel):>6}")
    print(f"5. ...of those, classified Mutual:              {len(mutual):>6}"
          f"   ({len(unclassified)} not yet classified)")
    # The label has to follow the flag: it read "most recent 150 mutual" next to
    # a count of 1,816 on the first --all-mutual run, which describes a
    # selection that was not used.
    selection_label = ("all classified mutual" if args.all_mutual
                        else f"most recent {args.top} mutual")
    print(f"6. Analysis subset ({selection_label}):  {len(subset):>6}")
    print()
    print(f"Redline-having requests by year: {year_hist(funnel)}")
    print(f"Mutual subset by year:           {year_hist(subset)}")
    if subset:
        print(f"Subset date range: {min(r['entry_date'] for r in subset if r['entry_date'])} "
              f"-> {max(r['entry_date'] for r in subset if r['entry_date'])}")
    print()
    print(f"Classification breakdown within redline-having requests: "
          f"{dict(Counter(r['nda_type'] or 'unclassified' for r in funnel))}")

    if unscanned_files:
        print(f"\nNOTE: {unscanned_files} .docx files in this scope are still unscanned — "
              f"stages 4-6 will grow. Run scan_tracked_changes.py to completion first.")

    if args.out:
        payload = {
            "scope": {"request_type": rt, "geography": geo,
                       # Which selection was used, not just its size — a reader
                       # of the methodology page should not have to infer
                       # "whole population" from a count.
                       "selection": "all classified mutual" if args.all_mutual
                                     else f"{args.top} most recent mutual",
                       "top": None if args.all_mutual else args.top},
            "counts": {
                "total_requests": total, "with_docx": with_docx, "scanned_requests": scanned,
                "unscanned_docx_files": unscanned_files,
                "with_tracked_changes_redline": len(funnel),
                "mutual_with_redline": len(mutual), "unclassified_with_redline": len(unclassified),
                "subset_size": len(subset),
            },
            "by_year": {"redline_having": year_hist(funnel), "mutual_subset": year_hist(subset)},
            "subset_request_ids": [r["request_id"] for r in subset],
        }
        Path(args.out).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {args.out}")
    conn.close()


if __name__ == "__main__":
    main()
