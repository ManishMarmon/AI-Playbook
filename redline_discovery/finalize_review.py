"""
B2 (Golden Rules review) — turns the raw workflow result into the dashboard's
`golden_rules_findings.json`.

Two things happen here that deliberately do NOT happen inside the workflow:

1. **suggested_language is attached here, in Python, keyed by rule_id.** It's the
   playbook's own `preferred_language` — long, lawyer-authored clause text. Round-tripping
   that through an LLM risks silent paraphrase of language that must be reproduced
   verbatim, so the workflow never sees it and never echoes it. Violations only: a
   satisfied rule needs no replacement wording. `suggested_language_source_tag` rides
   along so the UI can warn when the wording is an unvetted draft (the playbook
   explicitly marks those "do not auto-generate redlines from unsupervised").
2. **The `skipped` array and coverage totals are merged in**, from run_review.py's
   `review_skipped.json`, so the dashboard can state honestly how much of the request
   population the review actually covered rather than implying full coverage.

Usage:
    python finalize_review.py                       # uses output/golden_rules_raw_result.json
    python finalize_review.py --raw <path> --copy-to-frontend
"""

import argparse
import json
from pathlib import Path

import config

PLAYBOOKS_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "playbooks"
FRONTEND_DATA_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "data"

# Only CONFIRMED violations get suggested replacement wording. `flaggedInaccurate`
# rows are findings the adversarial verify pass rejected — offering language to "fix"
# a violation that a second pass concluded doesn't hold up invites an attorney to
# redline something that isn't actually broken. The rule's own preferred_language is
# still reachable via the playbook/drafting tool if someone disagrees with the
# rejection; it just isn't served up as an actionable suggestion here.
SUGGESTION_BUCKETS = ("violations",)
ALL_BUCKETS = ("violations", "flaggedInaccurate", "satisfied", "notApplicableOrNotFound")


def _load_rules_by_id() -> dict:
    """rule_id -> rule, across every playbook (rule_ids are unique per playbook and
    findings carry playbook_id, so a flat map is enough as long as ids don't collide
    across playbooks — asserted below rather than assumed)."""
    manifest = json.loads((PLAYBOOKS_DIR / "manifest.json").read_text(encoding="utf-8"))
    rules: dict[str, dict] = {}
    for entry in manifest:
        playbook = json.loads((PLAYBOOKS_DIR / entry["file"]).read_text(encoding="utf-8"))
        for rule in playbook:
            rid = rule["rule_id"]
            if rid in rules:
                raise SystemExit(
                    f"rule_id {rid!r} appears in more than one playbook — suggested_language "
                    f"lookup would be ambiguous. Key the map by (playbook_id, rule_id) instead."
                )
            rules[rid] = rule
    return rules


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=None,
                         help="Raw workflow result JSON (default: output/golden_rules_raw_result.json)")
    parser.add_argument("--copy-to-frontend", action="store_true",
                         help="Also copy the result into mclegal-frontend/public/data/")
    args = parser.parse_args()

    raw_path = Path(args.raw) if args.raw else config.OUTPUT_DIR / "golden_rules_raw_result.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    rules_by_id = _load_rules_by_id()

    out = {}
    attached = 0
    unvetted = 0
    unknown_rule_ids = set()

    for bucket in ALL_BUCKETS:
        rows = raw.get(bucket) or []
        finalized = []
        for row in rows:
            row = dict(row)
            rule = rules_by_id.get(row.get("rule_id"))
            if rule is None:
                unknown_rule_ids.add(row.get("rule_id"))
            preferred = (rule or {}).get("preferred_language")
            if bucket in SUGGESTION_BUCKETS and preferred:
                row["suggested_language"] = preferred
                row["suggested_language_source_tag"] = (rule or {}).get("source_tag")
                attached += 1
                if "unvetted" in (row["suggested_language_source_tag"] or "").lower():
                    unvetted += 1
            else:
                row["suggested_language"] = None
                row["suggested_language_source_tag"] = None
            finalized.append(row)
        out[bucket] = finalized

    skipped_path = config.OUTPUT_DIR / "review_skipped.json"
    skipped = json.loads(skipped_path.read_text(encoding="utf-8")) if skipped_path.exists() else []
    out["skipped"] = skipped

    reviewed = raw.get("requestsReviewed", 0)
    # Four different numbers that are easy to conflate — the dashboard needs all of
    # them to state coverage honestly rather than implying the whole population was
    # reviewed:
    #   requestsTotal    — requests run_review.py looked at when selecting candidates
    #   requestsSkipped  — of those, ones with no matching playbook (or no usable text)
    #   requestsInScope  — of those, ones that DID match a playbook (review candidates)
    #   requestsSubmitted/requestsReviewed — of the in-scope ones, how many this
    #                      particular workflow run was actually handed / completed
    manifest_path = config.OUTPUT_DIR / "review_run_manifest.json"
    in_scope = 0
    if manifest_path.exists():
        in_scope = len(json.loads(manifest_path.read_text(encoding="utf-8")).get("requestIds") or [])

    out["requestsReviewed"] = reviewed
    out["requestsSubmitted"] = raw.get("requestsTotal", reviewed)
    out["requestsInScope"] = in_scope or out["requestsSubmitted"]
    out["requestsFailed"] = raw.get("requestsFailed", 0)
    out["failedRequestIds"] = raw.get("failedRequestIds", [])
    out["requestsSkipped"] = len(skipped)
    out["requestsTotal"] = out["requestsInScope"] + len(skipped)
    out["verificationFailedCount"] = raw.get("verificationFailedCount", 0)
    out["scanChunksFailed"] = raw.get("scanChunksFailed", 0)
    out["scanChunksTotal"] = raw.get("scanChunksTotal", 0)

    if unknown_rule_ids:
        raise SystemExit(
            f"{len(unknown_rule_ids)} rule_id(s) in the workflow result have no matching rule "
            f"in any playbook: {sorted(unknown_rule_ids)[:10]} — refusing to write a findings "
            f"file with unresolvable rules."
        )

    out_path = config.OUTPUT_DIR / "golden_rules_findings.json"
    out_path.write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    print("=" * 50)
    print(f"Violations:              {len(out['violations'])}")
    print(f"Flagged inaccurate:      {len(out['flaggedInaccurate'])}")
    print(f"Satisfied:               {len(out['satisfied'])}")
    print(f"Not applicable/found:    {len(out['notApplicableOrNotFound'])}")
    print(f"Skipped (no playbook):   {out['requestsSkipped']}")
    print(f"Coverage: {reviewed} reviewed / {out['requestsSubmitted']} submitted / "
          f"{out['requestsInScope']} in scope / {out['requestsTotal']} total requests")
    print(f"suggested_language attached: {attached} ({unvetted} flagged unvetted-draft)")
    print("=" * 50)
    print(f"Wrote {out_path}")

    if args.copy_to_frontend:
        FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
        dest = FRONTEND_DATA_DIR / "golden_rules_findings.json"
        dest.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Copied to {dest}")


if __name__ == "__main__":
    main()
