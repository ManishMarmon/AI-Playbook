"""
Playbook synthesis (Cluster + Draft), ported from
workflows/synthesize_playbook_workflow.js to run against Azure OpenAI
(gpt-5.6-luna by default) instead of Claude Code's Workflow tool — see
AZURE_OPENAI_PORT_PLAN.md.

Same two-stage design as the Claude version, on purpose:
  1. Cluster — one call, groups all confirmed findings into distinct rule
     topics + categories.
  2. Draft — one call per topic, drafts a Golden-Rules-shaped rule from the
     pattern across that topic's findings only.

One deliberate efficiency improvement over the Claude version: the Claude
workflow's draft prompt tells the agent to re-read the ENTIRE findings file
and find the ones matching its topic itself (cheap for an agent with file
tools; wasteful for a raw API call). This version pre-filters findings to
just the topic's matches in Python and embeds only those — smaller prompts,
same result, since the filtering logic (clause_name membership) is
deterministic and doesn't need the model to do it.

Output shape matches what finalize_playbook.py expects from a saved
synthesize_playbook_workflow.js task result
({"result": {topicsTotal, rulesDrafted, avgRuleBodyChars, fieldsOverCeiling,
rules: [...]}}), so finalize_playbook.py works against this script's output
unchanged.

Usage:
    python azure_playbook_synthesis.py --findings output/real_estate_gpt_clause_findings.json \
        --out output/real_estate_gpt_synthesis_raw.json
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import llm_azure
from llm_azure import call_structured, StructuredCallFailed
from cost_log import append_cost_log_entry

MAX_WORKERS = 6

CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string"},
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "category_prefix": {"type": "string"},
                    "matching_clause_names": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic_id", "title", "category", "category_prefix", "matching_clause_names"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["topics"],
    "additionalProperties": False,
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "priority": {"type": "string", "enum": ["MUST PRESS", "PRESS", "MANAGE", "ACCEPT+NOTE"]},
        "applies_to": {"type": "string"},
        "where_to_look": {"type": "string"},
        "required": {"type": "string"},
        "fallback": {"type": "string"},
        "escalate_if": {"type": "string"},
        "flag_if": {"type": "array", "items": {"type": "string"}},
        "preferred_language": {"type": "string"},
        "confidence_note": {"type": "string"},
    },
    "required": ["title", "priority", "applies_to", "where_to_look", "required", "fallback",
                 "escalate_if", "flag_if", "preferred_language", "confidence_note"],
    "additionalProperties": False,
}

CEILINGS = {"where_to_look": 200, "required": 300, "fallback": 420, "escalate_if": 290, "preferred_language": 850}


def cluster_prompt(findings_json_text: str) -> str:
    return f"""Below is an array of VERIFIED, real clause-level findings from actual contract negotiations — each shows a clause_name, what the clause said before negotiation vs. after (spirit_before/spirit_after), why it was likely changed (negotiation_intent), and how significant the change was.

<<<FINDINGS_JSON>>>
{findings_json_text}
<<<END_FINDINGS_JSON>>>

The clause_name field was assigned per-finding by an earlier pass and is NOT already normalized — near-duplicate wording will exist (e.g. "Return of Confidential Information" vs "Return/Destruction of Materials" vs "Return of Documents on Termination" may all be the same underlying negotiating topic).

Your job: read through ALL findings and group them into a set of distinct RULE TOPICS — one topic per genuinely distinct negotiating issue a contracts attorney would treat as its own checklist item. Merge near-duplicate clause_name variants into one topic; keep genuinely different issues separate even if superficially similar (e.g. "assignment by tenant" and "subletting by tenant" are related but usually distinct topics).

For each topic, also assign it to a CATEGORY — a broader risk-area grouping (the same idea as how a playbook might group topics under headings like "Liability & Indemnity", "Payment & Money", "Term & Termination" — but invent categories that actually fit what's in THIS data; do not force findings into categories that don't fit, and do not assume in advance what categories should exist). Aim for roughly 6-12 categories total, each covering several topics.

Only create a topic for something that appears in at least 2 findings (ideally more) — a single one-off finding usually isn't a stable enough pattern to build a rule from; skip it rather than inventing a topic around one data point. Every finding's clause_name should map to at most one topic's matching_clause_names list.

Also assign each CATEGORY (not each topic) a short rule-id prefix, 2-4 uppercase letters, e.g. "LIA" for "Liability & Indemnity" or "PAY" for "Payment & Money" — this becomes part of every rule's id in that category (e.g. LIA-01), so every category's prefix must be distinct from every other category's prefix in this same response. Repeat the same category_prefix on every topic that shares a category."""


def draft_prompt(topic: dict, matching_findings: list) -> str:
    findings_json_text = json.dumps(matching_findings, indent=2)
    return f"""You are drafting ONE rule for a Golden Rules contract-review playbook, in the same style as an attorney-authored playbook (fields: priority, applies_to, where_to_look, required, fallback, escalate_if, flag_if, preferred_language).

This rule covers the topic "{topic['title']}" (category: {topic['category']}). Below are the findings whose clause_name matches this topic — {len(matching_findings)} distinct clause-name variant(s).

<<<FINDINGS_JSON>>>
{findings_json_text}
<<<END_FINDINGS_JSON>>>

Each finding shows a REAL negotiated change: what a clause said before negotiation (spirit_before) vs. after (spirit_after), across a real contract between a Marmon business unit and a real counterparty. Treat "before" as roughly what counterparties/their counsel tend to propose, and "after" (the negotiated/signed position) as roughly where Marmon's side has actually been landing this issue in practice.

Synthesize ONE rule from the PATTERN across all of this topic's findings (not any single instance):
- priority: MUST PRESS if the findings show this is consistently contested and high-stakes (significance mostly "high", the position moves substantially); PRESS if real but more moderate; MANAGE if it's a real issue but lower-stakes or inconsistently pushed; ACCEPT+NOTE if it's usually just noted/accepted rather than fought over.
- applies_to: this field is matched EXACTLY by downstream code, so it must be either the literal string "All contract types", or a short specific sub-type name under 40 characters (e.g. "Ground lease", "Purchase agreement") if — and only if — the findings clearly show this rule doesn't apply to every deal this playbook covers. Do NOT write a descriptive sentence or parenthetical here (that belongs in where_to_look or confidence_note instead) — an exact-match value is required for the rule to ever actually get selected.
- where_to_look: ONE short sentence naming the clause/section type where this shows up. Target ~110 characters, hard ceiling 200.
- required: the position to ask for first, stated as a decided instruction. Target ~105 characters, hard ceiling 300.
- fallback: the position to accept if "required" isn't achievable. Target ~125 characters, hard ceiling 420.
- escalate_if: what must never be accepted without an attorney. Target ~125 characters, hard ceiling 290.
- flag_if: 3-5 short, individually-testable detection signals. Each ONE sentence, no sub-clauses or parentheticals.
- preferred_language: contract clause language implementing REQUIRED. Target ~390 characters, hard ceiling 850. One clause, not a whole section — no RECITALS blocks, no multi-paragraph agreements, no bracketed fill-in forms unless a single placeholder is genuinely unavoidable.
- confidence_note: ONE sentence on how many findings and how consistent (e.g. "Based on 4 findings across 4 counterparties, consistent direction" or "Based on 2 findings with mixed signals — especially provisional").

WRITING STYLE — this matters as much as the substance. You are writing as a senior lawyer who has ALREADY decided the position, recording it for a reviewer to act on. You are NOT writing a memo justifying your reasoning.

- State conclusions. Never show your work inside a rule field.
- No hedging inside where_to_look / required / fallback / escalate_if / flag_if / preferred_language. Words like "typically", "generally", "may", "consider whether", "it is unclear", "informed by the findings" do not belong there.
- No evidence talk in the rule fields — no counterparty names, no finding counts, no "the three findings underlying this rule". ALL of that goes in confidence_note and nowhere else.
- No enumerated sub-conditions inside a single field (no "(1)... (2)... (3)..." chains). If a field needs that many parts, it is really two topics or belongs in flag_if as separate entries.
- Avoid parentheticals and em-dash asides. One idea per sentence.
- Uncertainty is expressed by choosing a LOWER priority (MANAGE instead of MUST PRESS) and by saying so in confidence_note — never by qualifying the rule text itself.

If the findings for this topic are sparse or inconsistent, lean toward MANAGE and say so plainly in confidence_note — but still write the rule itself as a clean, decided position."""


def body_chars(draft: dict) -> int:
    total = sum(len(draft.get(f, "") or "") for f in CEILINGS)
    total += sum(len(s) for s in draft.get("flag_if", []) or [])
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True,
                         help="Path to a confirmed-findings JSON array (see extract_confirmed_findings.py "
                              "or azure_clause_tagging.py's output's result.confirmed)")
    parser.add_argument("--out", required=True, help="Path to write the raw synthesis result to")
    parser.add_argument("--sample-size", required=True, type=int,
                         help="Total requests processed by the tagging stage this findings file came from "
                              "(tagging raw output's result.requestsProcessed) — the denominator for each "
                              "topic's evidence_pct, i.e. 'this issue showed up in N%% of the contracts we "
                              "actually looked at', not just N%% of the ones that had ANY finding.")
    parser.add_argument("--min-evidence-pct", type=float, default=15.0,
                         help="A topic needs findings from at least this %% of --sample-size distinct "
                              "requests to become a rule in the main playbook; below that (but still "
                              "meeting the cluster stage's own 2+ finding floor) it's still drafted, but "
                              "routed to result.suggested_rules instead of result.rules — see "
                              "finalize_playbook.py, which writes that to a '<id>-suggested.json' sidecar "
                              "rather than discarding it.")
    args = parser.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    print(f"Loaded {len(findings)} confirmed findings from {args.findings}")

    usage_dir = Path(__file__).parent / "output" / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    llm_azure.set_usage_log_path(usage_dir / f"playbook_synthesis_{int(time.time())}.jsonl")

    run_start = time.time()

    print(f"Clustering via Azure OpenAI (model={llm_azure.DEFAULT_MODEL})...")
    findings_json_text = json.dumps(findings, indent=2)
    try:
        cluster_result = call_structured(cluster_prompt(findings_json_text), CLUSTER_SCHEMA, "cluster_topics",
                                          call_label="cluster")
    except StructuredCallFailed as e:
        raise SystemExit(f"Cluster call failed after retries: {e}")

    topics = cluster_result.get("topics", [])
    print(f"Clustered into {len(topics)} topics")

    by_clause_name = {}
    for f in findings:
        by_clause_name.setdefault(f["clause_name"], []).append(f)

    def draft_one(topic):
        matching = [f for name in topic["matching_clause_names"] for f in by_clause_name.get(name, [])]
        evidence_count = len(matching)
        evidence_requests = len({f["request_id"] for f in matching if f.get("request_id") is not None})
        evidence_pct = round(evidence_requests / args.sample_size * 100, 1) if args.sample_size else 0.0
        try:
            draft = call_structured(draft_prompt(topic, matching), DRAFT_SCHEMA, "draft_rule",
                                     call_label=f"draft:{topic['topic_id']}")
            return {
                "topic": topic, "draft": draft,
                "evidence_count": evidence_count, "evidence_requests": evidence_requests,
                "evidence_pct": evidence_pct,
            }
        except StructuredCallFailed as e:
            print(f"  Topic {topic['topic_id']} ({topic['title']}): draft call failed ({e}) — excluded")
            return None

    print("Drafting rules...")
    drafted = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(draft_one, t) for t in topics]
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result:
                drafted.append(result)
            if i % 5 == 0 or i == len(topics):
                print(f"...{i}/{len(topics)} topics processed")

    over_ceiling = []
    for entry in drafted:
        draft = entry["draft"]
        for field, ceiling in CEILINGS.items():
            length = len(draft.get(field, "") or "")
            if length > ceiling:
                over_ceiling.append(f"{entry['topic']['topic_id']}.{field}={length} (max {ceiling})")

    avg_body = round(sum(body_chars(e["draft"]) for e in drafted) / len(drafted)) if drafted else 0

    confirmed_tier = [e for e in drafted if e["evidence_pct"] >= args.min_evidence_pct]
    suggested_tier = [e for e in drafted if e["evidence_pct"] < args.min_evidence_pct]

    print(f"\nDone: {len(drafted)}/{len(topics)} topics drafted into rules")
    print(f"  {len(confirmed_tier)} meet the {args.min_evidence_pct}% evidence bar -> main playbook")
    print(f"  {len(suggested_tier)} below the bar (but 2+ findings) -> suggested rules")
    print(f"Avg rule body: {avg_body} chars (Freo reference ~1057; Claude Real Estate v2 ~1653)")
    if over_ceiling:
        print(f"{len(over_ceiling)} field(s) over ceiling: {', '.join(over_ceiling)}")

    def rule_dict(e):
        return {
            "title": e["draft"]["title"],
            "category": e["topic"]["category"],
            "category_prefix": e["topic"]["category_prefix"],
            "priority": e["draft"]["priority"],
            "applies_to": e["draft"]["applies_to"],
            "where_to_look": e["draft"]["where_to_look"],
            "required": e["draft"]["required"],
            "fallback": e["draft"]["fallback"],
            "escalate_if": e["draft"]["escalate_if"],
            "flag_if": e["draft"]["flag_if"],
            "preferred_language": e["draft"]["preferred_language"],
            "source_tag": "Unvetted draft - counsel review needed",
            "confidence_note": e["draft"]["confidence_note"],
            "matching_clause_names": e["topic"]["matching_clause_names"],
            "evidence_count": e["evidence_count"],
            "evidence_requests": e["evidence_requests"],
            "evidence_pct": e["evidence_pct"],
        }

    output = {
        "result": {
            "topicsTotal": len(topics),
            "rulesDrafted": len(drafted),
            "sampleSize": args.sample_size,
            "minEvidencePct": args.min_evidence_pct,
            "avgRuleBodyChars": avg_body,
            "fieldsOverCeiling": over_ceiling,
            "rules": [rule_dict(e) for e in confirmed_tier],
            "suggested_rules": [rule_dict(e) for e in suggested_tier],
        }
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {args.out}")

    wall_elapsed = time.time() - run_start
    totals = llm_azure.get_usage_totals()
    totals["wall_seconds"] = wall_elapsed
    append_cost_log_entry("playbook_synthesis", llm_azure.DEFAULT_MODEL, len(topics), totals)


if __name__ == "__main__":
    main()
