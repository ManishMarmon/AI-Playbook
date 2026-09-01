"""
Retrofits evidence_count/evidence_requests/evidence_pct onto an EXISTING,
already-drafted playbook's rules — for a playbook that shipped before
evidence tiering existed (see azure_playbook_synthesis.py) and whose rule
text shouldn't be discarded and re-drafted by a different model just to add
this. Uses each rule's own matching_clause_names to look up which confirmed
findings support it, exactly the same lookup azure_playbook_synthesis.py
does at draft time — this script just does it after the fact, with no LLM
call at all.

Requires the playbook's rules to carry matching_clause_names (true for any
playbook mined from real findings, whether via the Claude Workflow tool or
azure_playbook_synthesis.py). An attorney-authored playbook with no findings
lineage (e.g. Freo Group AU) has nothing to retrofit — there's no findings
file it was drafted from, so there's no evidence trail to compute. Refuses
rather than fabricating one.

Splits into two tiers at --min-evidence-pct, same convention as
azure_playbook_synthesis.py: the confirmed tier overwrites the main
"<id>.json"; the rest go to "<id>-suggested.json" (merged with whatever's
already there, if anything). Rule ids are NOT renumbered — these already
shipped and may be referenced elsewhere.

Usage:
    python retrofit_evidence_tiers.py --playbook real-estate-usa \
        --findings output/real_estate_clause_findings.json --sample-size 50
"""

import argparse
import json
from pathlib import Path

PLAYBOOKS_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "playbooks"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playbook", required=True, help="Manifest id, e.g. real-estate-usa")
    parser.add_argument("--findings", required=True,
                         help="The confirmed-findings JSON this playbook was originally drafted from")
    parser.add_argument("--sample-size", required=True, type=int,
                         help="Total requests processed by the tagging run this findings file came from")
    parser.add_argument("--min-evidence-pct", type=float, default=15.0)
    parser.add_argument("--min-evidence-requests", type=int, default=None,
                         help="Absolute alternative to --min-evidence-pct, same meaning as in "
                              "azure_playbook_synthesis.py: a rule supported by at least this many "
                              "DISTINCT requests stays in the main playbook even if it misses the "
                              "percentage bar. The percentage bar does not survive a growing sample "
                              "— 15%% of 100 contracts is 15 requests, 15%% of 1,812 is 272, so a "
                              "pattern seen in 100 separate negotiations would be demoted despite "
                              "carrying far more evidence than anything in the 100-contract "
                              "playbook. Omit to gate on percentage alone.")
    args = parser.parse_args()

    manifest_path = PLAYBOOKS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next((e for e in manifest if e["id"] == args.playbook), None)
    if not entry:
        raise SystemExit(f"No manifest entry with id {args.playbook!r}")

    rules_path = PLAYBOOKS_DIR / entry["file"]
    rules = json.loads(rules_path.read_text(encoding="utf-8"))

    # Re-tiering has to be REVERSIBLE, so the pool is both tiers, not just the
    # main file. This script writes only the confirmed tier back to <id>.json
    # and the rest to the sidecar; reading only <id>.json would mean a second
    # run at a lower bar could never promote anything back, because the rules
    # the first run demoted are no longer in the file it reads. Choosing a bar
    # is a judgement an attorney should be able to revisit, so a rule must not
    # become unrecoverable just because one run put it in the sidecar.
    suggested_file = f"{args.playbook}-suggested.json"
    suggested_path = PLAYBOOKS_DIR / suggested_file
    if suggested_path.exists():
        known = {r.get("rule_id") for r in rules}
        carried = [r for r in json.loads(suggested_path.read_text(encoding="utf-8"))
                   if r.get("rule_id") not in known]
        if carried:
            print(f"Pooling {len(rules)} rule(s) from {entry['file']} with {len(carried)} "
                  f"previously-demoted rule(s) from {suggested_file} before re-tiering")
            rules = rules + carried

    missing_lineage = [r["rule_id"] for r in rules if "matching_clause_names" not in r]
    if missing_lineage:
        raise SystemExit(
            f"{len(missing_lineage)} rule(s) in {entry['file']} have no matching_clause_names "
            f"(e.g. {missing_lineage[:5]}) — this playbook has no findings lineage to retrofit "
            f"evidence stats from (attorney-authored playbooks like Freo Group AU are exactly this "
            f"case; don't run this against them)."
        )

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    by_clause_name: dict[str, list] = {}
    for f in findings:
        by_clause_name.setdefault(f["clause_name"], []).append(f)

    confirmed_tier, suggested_tier = [], []
    for rule in rules:
        matching = [f for name in rule["matching_clause_names"] for f in by_clause_name.get(name, [])]
        evidence_count = len(matching)
        evidence_requests = len({f["request_id"] for f in matching if f.get("request_id") is not None})
        evidence_pct = round(evidence_requests / args.sample_size * 100, 1) if args.sample_size else 0.0

        rule = {**rule, "evidence_count": evidence_count, "evidence_requests": evidence_requests,
                 "evidence_pct": evidence_pct}
        meets_pct = evidence_pct >= args.min_evidence_pct
        meets_absolute = (args.min_evidence_requests is not None
                          and evidence_requests >= args.min_evidence_requests)
        if meets_pct or meets_absolute:
            confirmed_tier.append(rule)
        else:
            suggested_tier.append(rule)

    bar = f"{args.min_evidence_pct}% of {args.sample_size} (= {args.sample_size * args.min_evidence_pct / 100:.0f} requests)"
    if args.min_evidence_requests is not None:
        bar += f" OR {args.min_evidence_requests}+ distinct requests"
    print(f"{args.playbook}: {len(confirmed_tier)}/{len(rules)} rules meet {bar}; "
          f"{len(suggested_tier)} move to the suggested tier")
    confirmed_ids = {r["rule_id"] for r in confirmed_tier}
    for r in sorted(confirmed_tier + suggested_tier, key=lambda r: -r["evidence_pct"]):
        tier = "CONFIRMED" if r["rule_id"] in confirmed_ids else "suggested"
        print(f"  [{tier:9s}] {r['rule_id']:12s} {r['evidence_pct']:5.1f}%  "
              f"({r['evidence_count']} findings, {r['evidence_requests']} requests)  {r['title']}")

    rules_path.write_text(json.dumps(confirmed_tier, indent=2), encoding="utf-8")
    print(f"\nWrote {len(confirmed_tier)} rules to {rules_path}")

    if suggested_tier:
        suggested_path.write_text(json.dumps(suggested_tier, indent=2), encoding="utf-8")
        print(f"Wrote {len(suggested_tier)} below-threshold rules to {suggested_path}")
        entry["suggestedRulesFile"] = suggested_file
    else:
        entry.pop("suggestedRulesFile", None)
        # Delete the sidecar rather than orphaning it. Dropping only the
        # manifest key hides it from the UI but leaves a file on disk that
        # still lists a now-promoted rule as below-threshold — and the next
        # run pools that file, so a stale copy is a real input, not just
        # clutter. Nothing is lost: an empty suggested tier means every rule
        # is in the main playbook.
        if suggested_path.exists():
            suggested_path.unlink()
            print(f"Removed {suggested_path.name} — every rule now meets the bar")

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
