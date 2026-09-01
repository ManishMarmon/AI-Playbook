"""
Rebuilds a clause-findings file from what Postgres already holds, in exactly
the shape azure_clause_tagging.py writes.

Why this exists: persisting per-request results made the tagging run
crash-safe, but the downstream chain (annotate_finding_sides.py ->
azure_playbook_synthesis.py) consumes a FILE, and the tagger only writes that
file after every request finishes. So a run that died at 99/100 left 99
requests' worth of expensive LLM work in the database with no way to use it
short of re-running. This closes that gap: the file is derivable from the
database at any moment, mid-run included.

Also useful for a partial smoke test — assemble what has completed so far and
push it through the rest of the pipeline to shake out integration problems
before the full run lands.

Usage:
    python export_clause_findings.py --population-tag nda-usa-mutual \
        --out output/nda_mutual_clause_findings.json
    python export_clause_findings.py --population-tag nda-usa-mutual \
        --out output/partial.json --expected-total 100
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import db

# The dashboard reads the UNWRAPPED result object (top-level confirmed/flagged/
# ...), not the {"result": {...}} envelope the pipeline passes around. Same
# location convention as finalize_review.py.
FRONTEND_DATA_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "data"


def build_payload(rows: dict, expected_total: int | None = None) -> dict:
    """rows: {request_id: stored result} from db.get_clause_tagging().

    Mirrors the tagger's own aggregation so the two can never disagree about
    what counts as confirmed."""
    succeeded = [r for r in rows.values() if not r["tagging_failed"]]
    failed = [r for r in rows.values() if r["tagging_failed"]]

    confirmed, flagged = [], []
    for r in succeeded:
        for f in r["verified_findings"]:
            verification = f.get("verification") or {}
            (confirmed if verification.get("accurate") else flagged).append(f)

    low_or_noise_count = sum(len(r["low_or_noise_findings"]) for r in succeeded)
    verification_failed = sum(r["verification_failed_count"] for r in succeeded)

    return {
        "result": {
            "confirmed": confirmed,
            "flagged": flagged,
            "lowOrNoiseCount": low_or_noise_count,
            "requestsProcessed": len(succeeded),
            # Honest about scope: without --expected-total the only total we can
            # attest to is what is stored, and claiming otherwise would make a
            # partial export look complete.
            "requestsTotal": expected_total if expected_total is not None else len(rows),
            "requestsFailed": len(failed),
            "failedRequestIds": sorted(r["request_id"] for r in failed),
            "verificationFailedCount": verification_failed,
            "exportedFromDb": True,
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--population-tag", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-total", type=int, default=None,
                         help="Total requests in the intended scope, when exporting a "
                              "partial run — otherwise the total is the stored count")
    parser.add_argument("--deploy", action="store_true",
                         help="Also write the unwrapped result to the dashboard's "
                              "public/data/clause_findings.json (the shape that page reads). "
                              "The existing file is backed up alongside it first — it may hold "
                              "a different population's findings, which this replaces.")
    args = parser.parse_args()

    conn = db.get_connection()
    rows = db.get_clause_tagging(conn, args.population_tag)
    conn.close()

    if not rows:
        raise SystemExit(
            f"No stored tagging results for population {args.population_tag!r}. "
            f"Check the tag (it is derived from the chunk directory name, e.g. "
            f"output/diff_chunks__nda-usa-mutual -> nda-usa-mutual)."
        )

    payload = build_payload(rows, args.expected_total)
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    r = payload["result"]
    models = {row.get("model") for row in rows.values() if row.get("model")}
    print(f"Exported {r['requestsProcessed']}/{r['requestsTotal']} request(s) "
          f"from Postgres -> {args.out}")
    print(f"  {len(r['confirmed'])} confirmed, {len(r['flagged'])} flagged, "
          f"{r['lowOrNoiseCount']} low/noise, {r['verificationFailedCount']} verify calls failed")
    if r["failedRequestIds"]:
        print(f"  tagging failed for: {r['failedRequestIds']}")
    if models:
        print(f"  model(s): {', '.join(sorted(models))}")
    if r["requestsProcessed"] < r["requestsTotal"]:
        print(f"  NOTE: partial export — {r['requestsTotal'] - r['requestsProcessed']} "
              f"request(s) of the stated scope are not yet stored")

    # Same guard extract_confirmed_findings.py carries, because this path hit the
    # identical trap from the other direction: annotate_finding_sides.py used to
    # write only to its JSON file, so an export straight from the database
    # produced 1,043 findings with a comparison_basis and not one position_side —
    # and the dashboard's provenance filter silently had nothing to match.
    with_basis = [f for f in r["confirmed"] + r["flagged"] if f.get("comparison_basis")]
    missing_side = [f for f in with_basis if not f.get("position_side")]
    if with_basis and missing_side:
        print(f"  WARNING: {len(missing_side)} of {len(with_basis)} findings carry a "
              f"comparison_basis but no position_side. The stored rows have not been "
              f"annotated. Run:\n"
              f"    python annotate_finding_sides.py --findings <payload> "
              f"--population-tag {args.population_tag}\n"
              f"  then re-export.")

    if args.deploy:
        FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = FRONTEND_DATA_DIR / "clause_findings.json"
        if dest.exists():
            # Kept, not overwritten: the file in place may be a different
            # population (e.g. the broader NDA run), and losing it would mean
            # re-running the tagger to get it back.
            prior = json.loads(dest.read_text(encoding="utf-8"))
            # A date-only stamp is NOT enough. Two deploys on one day made the
            # second backup overwrite the first, destroying the original file
            # this was meant to protect — which is the one failure a backup must
            # not have. Never clobber an existing backup.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            backup = dest.with_name(f"clause_findings.backup-{stamp}.json")
            seq = 2
            while backup.exists():
                backup = dest.with_name(f"clause_findings.backup-{stamp}-{seq}.json")
                seq += 1
            shutil.copy2(dest, backup)
            print(f"  backed up the existing dashboard file "
                  f"({len(prior.get('confirmed') or [])} confirmed, "
                  f"{'with' if (prior.get('confirmed') or [{}])[0].get('comparison_basis') else 'no'} "
                  f"provenance) -> {backup.name}")
        deployed = dict(r)
        deployed["generatedAt"] = datetime.now(timezone.utc).isoformat()
        deployed["populationTag"] = args.population_tag
        dest.write_text(json.dumps(deployed, indent=2), encoding="utf-8")
        print(f"  deployed to the dashboard -> {dest}")


if __name__ == "__main__":
    main()
