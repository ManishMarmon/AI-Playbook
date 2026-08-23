"""
Turns a synthesize_playbook_workflow.js raw task result into a real Golden
Rules playbook file + manifest entry — the AI-derived-playbook equivalent of
playbook_parser.py (which does the same job for a human-authored .docx).

Every playbook this produces is stamped source_tag "Unvetted draft - counsel
review needed" per rule (already set by the workflow) and status "ai_draft"
in the manifest — nothing here has been seen by a lawyer.

Rule IDs are assigned deterministically from a category -> short-prefix
mapping. Prefer letting synthesize_playbook_workflow.js's cluster step assign
`category_prefix` itself (it sees every category in the same call, so it can
avoid collisions); pass --category-prefixes only for an older raw result that
predates that field (e.g. the first Real Estate run).

Usage:
    python finalize_playbook.py --raw output/real_estate_synthesis_raw.json \
        --id real-estate-usa --label "US Real Estate" --jurisdiction "United States" \
        --contract-types "Real Estate" \
        --category-prefixes output/real_estate_category_prefixes.json
"""

import argparse
import json
from pathlib import Path

PLAYBOOKS_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "playbooks"

# applies_to is matched EXACTLY by contractAssembly.ts's selectRules() — a
# rule with a long descriptive applies_to silently never gets selected into a
# drafted contract (this exact bug happened on the first Real Estate run).
# Anything longer than this is almost certainly prose, not a real value.
_MAX_APPLIES_TO_LEN = 40


def _load_existing_rule_ids(exclude_playbook_id: str) -> set:
    manifest_path = PLAYBOOKS_DIR / "manifest.json"
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = set()
    for entry in manifest:
        if entry["id"] == exclude_playbook_id:
            continue
        rules = json.loads((PLAYBOOKS_DIR / entry["file"]).read_text(encoding="utf-8"))
        ids.update(r["rule_id"] for r in rules)
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True,
                         help="Path to the saved raw task output from a synthesize_playbook_workflow.js run")
    parser.add_argument("--id", required=True, help="Short id for this playbook, e.g. real-estate-usa")
    parser.add_argument("--label", required=True, help="Display label, e.g. 'US Real Estate'")
    parser.add_argument("--jurisdiction", required=True, help="e.g. 'United States'")
    parser.add_argument("--contract-types", required=True,
                         help="Comma-separated u_RequestType values this playbook covers, e.g. 'Real Estate'")
    parser.add_argument("--business-sectors", default="",
                         help="Comma-separated u_MarmonSector values, if this playbook is sector-scoped "
                              "(leave blank for a contract-type-wide playbook like Real Estate)")
    parser.add_argument("--status", default="ai_draft", choices=["ai_draft", "attorney_reviewed"])
    parser.add_argument("--category-prefixes", default=None,
                         help="Path to a JSON file mapping category name -> 2-4 letter prefix, for a raw "
                              "result predating the workflow's own category_prefix field")
    parser.add_argument("--prefix-namespace", default=None,
                         help="Short tag (e.g. 'RE') prepended to every category prefix, e.g. RE-DOC-01 "
                              "instead of DOC-01. The clustering step only sees categories within its own "
                              "playbook, so its auto-picked 2-4 letter prefixes (DOC, PAY, TRM...) can and "
                              "will collide with another playbook's prefixes — this namespaces them so "
                              "playbooks never need to coordinate prefix choices with each other.")
    args = parser.parse_args()

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    result = raw["result"]
    print(f"Topics: {result['topicsTotal']}, rules drafted: {result['rulesDrafted']}")

    prefix_map = {}
    if args.category_prefixes:
        prefix_map = json.loads(Path(args.category_prefixes).read_text(encoding="utf-8"))

    def prefix_for(rule: dict) -> str:
        if rule.get("category_prefix"):
            base = rule["category_prefix"]
        elif rule["category"] in prefix_map:
            base = prefix_map[rule["category"]]
        else:
            raise SystemExit(
                f"No prefix for category {rule['category']!r} — the raw result doesn't include "
                f"category_prefix and it's missing from --category-prefixes. Add it and re-run."
            )
        return f"{args.prefix_namespace}-{base}" if args.prefix_namespace else base

    counters: dict[str, int] = {}
    final_rules = []
    applies_to_warnings = []
    for r in result["rules"]:
        prefix = prefix_for(r)
        counters[prefix] = counters.get(prefix, 0) + 1
        rule_id = f"{prefix}-{counters[prefix]:02d}"

        applies_to = r["applies_to"]
        if applies_to != "All contract types" and len(applies_to) > _MAX_APPLIES_TO_LEN:
            applies_to_warnings.append((rule_id, applies_to))

        final_rules.append({
            "rule_id": rule_id,
            "title": r["title"],
            "priority": r["priority"],
            "applies_to": applies_to,
            "category": r["category"],
            "where_to_look": r["where_to_look"],
            "required": r["required"],
            "fallback": r["fallback"],
            "escalate_if": r["escalate_if"],
            "flag_if": r["flag_if"],
            "preferred_language": r["preferred_language"],
            "source_tag": r["source_tag"],
            "confidence_note": r["confidence_note"],
            "matching_clause_names": r["matching_clause_names"],
        })

    if applies_to_warnings:
        print("\nWARNING: these rules have a long/descriptive applies_to that selectRules() will "
              "never exact-match (fix by hand or re-run synthesis with the tightened prompt):")
        for rule_id, val in applies_to_warnings:
            print(f"  {rule_id}: {val[:80]!r}")

    existing_ids = _load_existing_rule_ids(exclude_playbook_id=args.id)
    collisions = existing_ids & {r["rule_id"] for r in final_rules}
    if collisions:
        raise SystemExit(f"Rule id collision with another playbook: {collisions} — "
                          f"pick different category prefixes for {args.id}.")

    PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    rules_path = PLAYBOOKS_DIR / f"{args.id}.json"
    rules_path.write_text(json.dumps(final_rules, indent=2), encoding="utf-8")
    print(f"\nWrote {len(final_rules)} rules to {rules_path}")

    manifest_path = PLAYBOOKS_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    manifest = [m for m in manifest if m["id"] != args.id]
    manifest.append({
        "id": args.id,
        "label": args.label,
        "jurisdiction": args.jurisdiction,
        "status": args.status,
        "contractTypes": [c.strip() for c in args.contract_types.split(",") if c.strip()],
        "businessSectors": [s.strip() for s in args.business_sectors.split(",") if s.strip()],
        "file": f"{args.id}.json",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
