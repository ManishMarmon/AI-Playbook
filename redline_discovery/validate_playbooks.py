"""
CI gate over the committed playbook JSON (mclegal-frontend/public/playbooks/)
— catches exactly the class of bug that shipped silently in the first Real
Estate playbook: a manifest/rule-data inconsistency that a human reviewing
prose wouldn't notice, but that breaks contractAssembly.ts's rule selection
at draft time. Pure data validation, no LLM calls, no network — fast enough
to run on every push.

Usage:
    python validate_playbooks.py
Exits non-zero (and prints every violation) if anything fails.
"""

import json
import sys
from pathlib import Path

PLAYBOOKS_DIR = Path(__file__).parent.parent / "mclegal-frontend" / "public" / "playbooks"

REQUIRED_RULE_FIELDS = [
    "rule_id", "title", "category", "priority", "applies_to",
    "where_to_look", "required", "fallback", "escalate_if", "flag_if",
    "preferred_language", "source_tag",
]

VALID_PRIORITIES = {"MUST PRESS", "PRESS", "MANAGE", "ACCEPT+NOTE"}
VALID_STATUSES = {"ai_draft", "attorney_reviewed"}


def validate() -> list[str]:
    errors = []

    manifest_path = PLAYBOOKS_DIR / "manifest.json"
    if not manifest_path.exists():
        return [f"manifest.json not found at {manifest_path}"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    seen_rule_ids: dict[str, str] = {}  # rule_id -> which playbook id first used it

    def validate_rules(playbook_id: str, rules: list[dict], contract_types: list[str], source_label: str):
        applies_to_vocab_mismatches = []
        for rule in rules:
            missing = [f for f in REQUIRED_RULE_FIELDS if f not in rule]
            if missing:
                errors.append(f"{playbook_id}/{rule.get('rule_id', '<no id>')} ({source_label}): missing fields {missing}")
                continue

            rule_id = rule["rule_id"]
            if rule_id in seen_rule_ids and seen_rule_ids[rule_id] != playbook_id:
                errors.append(
                    f"{playbook_id}/{rule_id} ({source_label}): rule_id collides with playbook "
                    f"{seen_rule_ids[rule_id]!r} — rule ids must be globally unique so findings can be "
                    f"recorded back against them"
                )
            seen_rule_ids[rule_id] = playbook_id

            if rule["priority"] not in VALID_PRIORITIES:
                errors.append(f"{playbook_id}/{rule_id} ({source_label}): priority {rule['priority']!r} not in {VALID_PRIORITIES}")

            # A rule with a comparison basis but no position side has lost its
            # attribution somewhere between synthesis and here. This is a real
            # regression that shipped: finalize_playbook.py's carry-through list
            # omitted the position_* fields, so a playbook whose synthesis found
            # 14 of 19 rules Marmon-attributable was written with none, the Word
            # document showed no side, and the reviewer hand-off asked counsel to
            # confirm all 19 as "side could not be confirmed". Nothing else
            # errored — the document just quietly said less than the data knew.
            # Rules that predate provenance carry neither field and are ignored.
            if rule.get("comparison_basis") and not rule.get("position_side"):
                errors.append(
                    f"{playbook_id}/{rule_id} ({source_label}): has comparison_basis "
                    f"{rule['comparison_basis']!r} but no position_side — the side attribution was "
                    f"dropped between synthesis and the playbook file. Check "
                    f"finalize_playbook.py's carry-through field list."
                )

            # The exact regression this validator exists to catch: a playbook
            # declaring more than one contract type needs contractAssembly.ts's
            # selectRules() to exact-match applies_to against one of them —
            # any other value is a rule that can NEVER be selected into a
            # drafted contract for any of this playbook's contract types.
            # (A single-contract-type playbook is immune — selectRules()
            # skips the applies_to filter entirely for those — but a
            # mismatch there still means the manifest's declared contract
            # type and the rule's own applies_to disagree, worth flagging.)
            applies_to = rule["applies_to"]
            if applies_to != "All contract types" and applies_to not in contract_types:
                applies_to_vocab_mismatches.append((rule_id, applies_to))

        if applies_to_vocab_mismatches and len(contract_types) > 1:
            for rule_id, val in applies_to_vocab_mismatches:
                errors.append(
                    f"{playbook_id}/{rule_id} ({source_label}): applies_to={val!r} is not 'All contract "
                    f"types' and not in this playbook's declared contractTypes {contract_types} — "
                    f"selectRules() will never select this rule for ANY of this playbook's contract types"
                )
        elif applies_to_vocab_mismatches:
            ids = ", ".join(f"{rid} ({val!r})" for rid, val in applies_to_vocab_mismatches)
            print(
                f"NOTE: {playbook_id} ({source_label}) declares a single contract type {contract_types}, "
                f"so these applies_to/contractTypes mismatches are harmless today (selectRules() skips "
                f"the applies_to filter for single-type playbooks) but would become load-bearing if "
                f"contractTypes is ever split into more than one value: {ids}"
            )

    for entry in manifest:
        playbook_id = entry.get("id", "<missing id>")
        contract_types = entry.get("contractTypes", [])

        if entry.get("status") not in VALID_STATUSES:
            errors.append(f"{playbook_id}: manifest status {entry.get('status')!r} not in {VALID_STATUSES}")

        rules_path = PLAYBOOKS_DIR / entry.get("file", "")
        if not rules_path.exists():
            errors.append(f"{playbook_id}: manifest points at missing file {entry.get('file')!r}")
            continue
        rules = json.loads(rules_path.read_text(encoding="utf-8"))

        if not rules:
            errors.append(f"{playbook_id}: {rules_path.name} has zero rules")

        validate_rules(playbook_id, rules, contract_types, source_label="main")

        suggested_file = entry.get("suggestedRulesFile")
        if suggested_file:
            suggested_path = PLAYBOOKS_DIR / suggested_file
            if not suggested_path.exists():
                errors.append(f"{playbook_id}: manifest points at missing suggestedRulesFile {suggested_file!r}")
            else:
                suggested_rules = json.loads(suggested_path.read_text(encoding="utf-8"))
                validate_rules(playbook_id, suggested_rules, contract_types, source_label="suggested")

    return errors


def main():
    errors = validate()
    if errors:
        print(f"\n{len(errors)} playbook validation failure(s):\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("All committed playbooks pass validation.")


if __name__ == "__main__":
    main()
