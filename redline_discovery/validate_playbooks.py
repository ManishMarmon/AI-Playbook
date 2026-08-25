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

        applies_to_vocab_mismatches = []
        for rule in rules:
            missing = [f for f in REQUIRED_RULE_FIELDS if f not in rule]
            if missing:
                errors.append(f"{playbook_id}/{rule.get('rule_id', '<no id>')}: missing fields {missing}")
                continue

            rule_id = rule["rule_id"]
            if rule_id in seen_rule_ids and seen_rule_ids[rule_id] != playbook_id:
                errors.append(
                    f"{playbook_id}/{rule_id}: rule_id collides with playbook {seen_rule_ids[rule_id]!r} "
                    f"— rule ids must be globally unique so findings can be recorded back against them"
                )
            seen_rule_ids[rule_id] = playbook_id

            if rule["priority"] not in VALID_PRIORITIES:
                errors.append(f"{playbook_id}/{rule_id}: priority {rule['priority']!r} not in {VALID_PRIORITIES}")

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
                    f"{playbook_id}/{rule_id}: applies_to={val!r} is not 'All contract types' and not "
                    f"in this playbook's declared contractTypes {contract_types} — selectRules() will "
                    f"never select this rule for ANY of this playbook's contract types"
                )
        elif applies_to_vocab_mismatches:
            ids = ", ".join(f"{rid} ({val!r})" for rid, val in applies_to_vocab_mismatches)
            print(
                f"NOTE: {playbook_id} declares a single contract type {contract_types}, so these "
                f"applies_to/contractTypes mismatches are harmless today (selectRules() skips the "
                f"applies_to filter for single-type playbooks) but would become load-bearing if "
                f"contractTypes is ever split into more than one value: {ids}"
            )

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
