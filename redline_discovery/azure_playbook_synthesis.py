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
import re
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import llm_azure
import provenance
from llm_azure import call_structured, NonRetryableCallFailed, StructuredCallFailed
from cost_log import append_cost_log_entry

MAX_WORKERS = 6

# Output caps a draft call escalates through. A rule body is ~1,400 characters,
# so anything past the first tier is reasoning, not prose — high effort on a
# 100k-token findings payload can spend a lot of it. Measured: 37 of 38 topics
# finished inside 45,000; the one that did not used exactly 45,000 with 74,790
# input, so the ceiling was the cap rather than the context. Unused caps cost
# nothing, and the service clamps a cap larger than the remaining context.
DRAFT_OUTPUT_CAPS = (45_000, 100_000)

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

ASSIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_name": {"type": "string"},
                    # "" means "belongs to none of them" — an explicit escape, so
                    # the model is never forced to file a name under a topic that
                    # doesn't fit just to satisfy the schema.
                    "topic_id": {"type": "string"},
                },
                "required": ["clause_name", "topic_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["assignments"],
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


# Clustering is given DISTINCT CLAUSE NAMES, not every finding.
#
# Its only job is to group clause_name variants into topics, and topics map back
# to findings purely by clause_name (`matching_clause_names`, see the draft loop)
# — so the per-finding payload was never used for the task. Passing it was fatal
# at population scale: the full array for 1,043 findings was already 467,168
# input tokens, of which 60% was fields this prompt never mentions (raw diff
# text, verification blocks, provenance). Scaled to the ~19,000 findings from
# the whole mutual-NDA population that is roughly 8.5M tokens — far past any
# context window, so synthesis would simply have failed.
#
# Collapsing to distinct names also gives the model something it previously had
# to infer by counting: each name's real finding_count, so the "appears in at
# least 2 findings" rule can be applied exactly rather than estimated.
_MAX_EXAMPLES_PER_NAME = 3
_EXAMPLE_CHARS = 220


def normalize_clause_name(name: str) -> str:
    """Case/punctuation-insensitive key for a clause name.

    The tagging pass writes clause_name free-form per finding, so the same topic
    arrives spelled a dozen ways that differ only in typography: 'Confidential
    Information - Exclusions', 'Confidential Information / Exclusions',
    'Confidential Information (Exclusions)', and the en-dash and em-dash
    versions of each. Collapsing those is deterministic arithmetic, not a
    judgement call, so it should never cost an LLM call — and merging them
    BEFORE clustering is what lets the ones that matter clear the 2-finding
    floor: on the 18,396-finding population it moved 2.5% of all findings from
    the one-off tail into countable topics (79.1% -> 81.6% of evidence).

    Deliberately conservative: only typography is erased. Genuinely different
    wording ('Return of Documents' vs 'Return or Destruction of Confidential
    Information') still arrives as separate names, because deciding those are
    the same negotiating issue is exactly the judgement the cluster call exists
    to make."""
    s = unicodedata.normalize("NFKD", name)
    for dash in ("–", "—", "−"):  # en dash, em dash, minus
        s = s.replace(dash, "-")
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def cluster_input(findings: list) -> list:
    """[{clause_name, finding_count, significance, examples[], raw_names[]}],
    most frequent first.

    One row per DISTINCT NEGOTIATING NAME after typography is normalised away
    (see normalize_clause_name) — clause_name carries the most common raw
    spelling for the model to read, and raw_names carries every spelling that
    row stands for, so findings can be mapped back exactly afterwards.

    Examples are capped and truncated: a few are enough to judge whether two
    names describe the same negotiating issue, and the cap is what keeps this
    bounded as the population grows."""
    by_key: dict = {}
    for f in findings:
        name = (f.get("clause_name") or "").strip()
        if not name:
            continue
        entry = by_key.setdefault(normalize_clause_name(name),
                                  {"clause_name": name, "finding_count": 0,
                                   "significance": Counter(), "examples": [],
                                   "_spellings": Counter()})
        entry["finding_count"] += 1
        entry["_spellings"][name] += 1
        entry["significance"][f.get("significance") or "unknown"] += 1
        if len(entry["examples"]) < _MAX_EXAMPLES_PER_NAME:
            entry["examples"].append({
                "negotiation_intent": (f.get("negotiation_intent") or "")[:_EXAMPLE_CHARS],
                "spirit_before": (f.get("spirit_before") or "")[:_EXAMPLE_CHARS],
                "spirit_after": (f.get("spirit_after") or "")[:_EXAMPLE_CHARS],
            })
    rows = []
    for e in by_key.values():
        spellings = e.pop("_spellings")
        # The most common spelling represents the group, ties broken
        # alphabetically so the same findings always produce the same prompt.
        display = sorted(spellings.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        rows.append({**e, "clause_name": display, "significance": dict(e["significance"]),
                     "raw_names": sorted(spellings)})
    return sorted(rows, key=lambda x: (-x["finding_count"], x["clause_name"]))


def prompt_rows(rows: list) -> str:
    """The cluster/assign payload as the model sees it. raw_names is bookkeeping
    for expand_to_raw_names and is withheld on purpose — showing the model a
    second list of near-identical spellings invites it to echo those back
    instead of the display name the prompt asks for, and costs tokens to do it.
    """
    return json.dumps([{k: v for k, v in r.items() if k != "raw_names"} for r in rows], indent=2)


def expand_to_raw_names(topics: list, rows: list) -> list:
    """Rewrites each topic's matching_clause_names from the display names the
    model saw into every raw spelling they stand for.

    Without this, a topic handed 'Confidential Information - Exclusions' would
    match only the findings that happened to use that exact typography and
    silently drop the other five spellings' findings from its evidence count —
    the same double-counting class of bug as dedupe_topic_claims, in the
    opposite direction."""
    # Keyed on the NORMALISED name, not the display spelling: the model is asked
    # to echo names verbatim and mostly does, but a returned name that differs
    # only in punctuation or case would otherwise fail to find its group and
    # take that group's other spellings' findings down with it.
    aliases = {normalize_clause_name(r["clause_name"]): r["raw_names"] for r in rows}
    for t in topics:
        expanded, seen = [], set()
        for name in t.get("matching_clause_names") or []:
            for raw in aliases.get(normalize_clause_name(name), [name]):
                if raw not in seen:
                    seen.add(raw)
                    expanded.append(raw)
        t["matching_clause_names"] = expanded
    return topics


def dedupe_topic_claims(topics: list, counts: dict) -> tuple:
    """Guarantees every clause name belongs to exactly ONE topic.

    The prompt asks for this, but a global invariant across dozens of topics is
    not something to leave to the model, and it does not hold: measured on the
    live 1,043-finding run, 96 of 495 clause names were claimed by more than one
    topic. Every duplicate double-counts its findings, inflating BOTH topics'
    evidence_requests and evidence_pct — which is what decides whether a rule
    reaches the main playbook or the suggested sidecar. The already-delivered
    playbook overstated evidence for exactly that reason.

    A contested name goes to the claimant with the most independent support (the
    total finding_count of the names only IT claims), so the name lands with the
    topic that is strongest in that area on its own merits rather than one that
    only looks strong because of contested names. Ties break on topic_id so the
    result is reproducible. Every reassignment is returned for logging — a
    silent reassignment would be its own kind of invisible.
    """
    claims: dict = {}
    for t in topics:
        for name in t.get("matching_clause_names") or []:
            claims.setdefault(name, []).append(t)

    contested = {n: ts for n, ts in claims.items() if len(ts) > 1}
    if not contested:
        return topics, []

    def independent_support(t):
        return sum(counts.get(n, 0) for n in (t.get("matching_clause_names") or [])
                   if len(claims.get(n, [])) == 1)

    report = []
    for name, claimants in sorted(contested.items()):
        # Most independent support wins; ties go to the LOWEST topic_id, which
        # is the topic the model emitted first (it tends to surface the more
        # prominent topics earlier). Keyed on topic_id rather than list position
        # so the outcome cannot depend on the order topics happen to arrive in.
        winner = sorted(claimants,
                        key=lambda t: (-independent_support(t), str(t.get("topic_id"))))[0]
        for t in claimants:
            if t is not winner:
                t["matching_clause_names"] = [n for n in t["matching_clause_names"] if n != name]
        report.append({
            "clause_name": name,
            "findings": counts.get(name, 0),
            "assigned_to": winner.get("title"),
            "removed_from": [t.get("title") for t in claimants if t is not winner],
        })
    return topics, report


def cluster_prompt(findings_json_text: str) -> str:
    return f"""Below is an array of DISTINCT CLAUSE NAMES observed across verified, real clause-level findings from actual contract negotiations. Each entry gives the clause_name, finding_count (how many separate findings carried that exact name), a significance breakdown, and up to 3 representative examples showing what the clause said before negotiation vs. after (spirit_before/spirit_after) and why it was likely changed (negotiation_intent).

<<<FINDINGS_JSON>>>
{findings_json_text}
<<<END_FINDINGS_JSON>>>

The clause_name field was assigned per-finding by an earlier pass and is NOT already normalized — near-duplicate wording will exist (e.g. "Return of Confidential Information" vs "Return/Destruction of Materials" vs "Return of Documents on Termination" may all be the same underlying negotiating topic).

Your job: read through ALL of these clause names and group them into a set of distinct RULE TOPICS — one topic per genuinely distinct negotiating issue a contracts attorney would treat as its own checklist item. Merge near-duplicate clause_name variants into one topic; keep genuinely different issues separate even if superficially similar (e.g. "assignment by tenant" and "subletting by tenant" are related but usually distinct topics).

Every clause_name in the input must appear in at most one topic's matching_clause_names list. Use each entry's finding_count when judging whether a topic has enough support — a topic's support is the SUM of the finding_counts of the clause names you assign to it.

For each topic, also assign it to a CATEGORY — a broader risk-area grouping (the same idea as how a playbook might group topics under headings like "Liability & Indemnity", "Payment & Money", "Term & Termination" — but invent categories that actually fit what's in THIS data; do not force findings into categories that don't fit, and do not assume in advance what categories should exist). Aim for roughly 6-12 categories total, each covering several topics.

Only create a topic whose combined finding_count is at least 2 (ideally more) — a single one-off finding usually isn't a stable enough pattern to build a rule from; skip it rather than inventing a topic around one data point.

Also assign each CATEGORY (not each topic) a short rule-id prefix, 2-4 uppercase letters, e.g. "LIA" for "Liability & Indemnity" or "PAY" for "Payment & Money" — this becomes part of every rule's id in that category (e.g. LIA-01), so every category's prefix must be distinct from every other category's prefix in this same response. Repeat the same category_prefix on every topic that shares a category."""


def assign_prompt(topics: list, tail_json_text: str) -> str:
    """Second clustering pass: file the one-off clause names into the topics the
    first pass already established.

    Why a second pass instead of one big call: the first pass must see every
    name it might merge, and its answer must echo every name back, so its cost
    grows with the name count in BOTH directions. At population scale that is
    what killed it — 4,974 names became a 916k-token prompt, leaving the service
    no context left to answer in. The names that force that size are the tail:
    3,390 of them appear in exactly ONE finding out of 18,396.

    Those names cannot create a topic on their own (the 2-finding floor exists
    precisely because one data point is not a pattern), but their findings still
    count as evidence for topics that DO exist — so discarding them would
    understate 18% of the evidence. Assigning them afterwards, in batches, gets
    both: the expensive merge judgement runs once over the names that can form
    topics, and the tail is placed by a cheap, parallel, bounded call whose
    answer is just a name and an id."""
    catalog = json.dumps(
        [{"topic_id": t["topic_id"], "title": t["title"], "category": t["category"],
          # A few member names show the model what each topic actually covers —
          # far more informative than the title alone, and cheap.
          "example_clause_names": (t.get("matching_clause_names") or [])[:6]}
         for t in topics], indent=2)
    return f"""Below is a catalog of established RULE TOPICS from a contract playbook, followed by a list of additional CLAUSE NAMES that have not yet been filed under any topic.

<<<TOPICS_JSON>>>
{catalog}
<<<END_TOPICS_JSON>>>

<<<UNFILED_CLAUSE_NAMES_JSON>>>
{tail_json_text}
<<<END_UNFILED_CLAUSE_NAMES_JSON>>>

Each unfiled entry gives the clause_name, its finding_count, a significance breakdown, and up to 3 representative examples showing what the clause said before negotiation vs. after (spirit_before/spirit_after) and why it was likely changed (negotiation_intent).

Your job: for EVERY unfiled clause name, decide which ONE existing topic it belongs to — the topic covering the same underlying negotiating issue, judged on what the examples actually show, not on surface word overlap in the name. Return its topic_id.

Do not invent new topics. Do not return a topic_id that is not in the catalog above.

If a clause name genuinely does not belong to any topic in the catalog, return an empty string "" for its topic_id. Use that escape rather than forcing a poor fit — a name filed under the wrong topic corrupts that topic's evidence, which is worse than leaving it unfiled. But do not overuse it either: most of these are variant wordings of issues the catalog already covers.

Return exactly one assignment for every clause_name given, using the clause_name string verbatim as it appears above."""


def draft_prompt(topic: dict, matching_findings: list, evidence_total: int = None) -> str:
    findings_json_text = json.dumps(matching_findings, indent=2)
    total = evidence_total if evidence_total is not None else len(matching_findings)
    # Stated explicitly when the prompt carries a sample, so confidence_note
    # reports the evidence the rule ACTUALLY rests on. Told that it is reading
    # 400 findings, the model would write "based on 400 findings" for a rule
    # supported by 1,900 — understating its own evidence in the one field an
    # attorney reads to judge how much to trust it.
    scope = (f"Below are {len(matching_findings)} findings matching this topic, drawn from across "
             f"{total} total matching findings — a representative sample spanning as many separate "
             f"contracts as possible. Judge the pattern from these, but when you state how much "
             f"evidence supports this rule in confidence_note, use the TOTAL of {total} findings."
             if len(matching_findings) < total else
             f"Below are all {total} findings whose clause_name matches this topic.")
    return f"""You are drafting ONE rule for a Golden Rules contract-review playbook, in the same style as an attorney-authored playbook (fields: priority, applies_to, where_to_look, required, fallback, escalate_if, flag_if, preferred_language).

This rule covers the topic "{topic['title']}" (category: {topic['category']}). {scope}

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


def sample_for_draft(matching: list, cap: int) -> tuple:
    """(findings to show the model, was_sampled) — at most `cap`, spread across
    as many distinct requests as possible.

    The draft prompt embeds a topic's findings in full, so its size grows with
    the topic's support. That is fine at sample scale (the largest topic in the
    150-request run carried 158 findings, ~55k tokens) and fatal at population
    scale: the same topic covers ~65% of contracts, so at 1,812 requests it
    reaches ~1,900 findings and ~660k tokens — the same wall that killed the
    cluster call, reached from the other direction.

    Only the MODEL's view is capped. evidence_count, evidence_requests,
    evidence_pct, the provenance rollup and the side counts are all computed in
    Python from the complete list, so the numbers an attorney reads stay exact —
    capping the prompt must not quietly shrink the evidence a rule claims.

    Selection is round-robin across requests, not the first N: a topic's
    findings arrive grouped by clause name, so a head slice can be dominated by
    a handful of contracts. The prompt asks for the pattern ACROSS
    negotiations, which makes breadth of requests the property worth
    preserving. Requests are visited in sorted order so the same findings always
    produce the same prompt.
    """
    if not cap or len(matching) <= cap:
        return matching, False

    by_request: dict = {}
    for f in matching:
        by_request.setdefault(f.get("request_id"), []).append(f)
    order = sorted(by_request, key=lambda r: (r is None, r))

    picked, depth = [], 0
    while len(picked) < cap:
        progressed = False
        for r in order:
            bucket = by_request[r]
            if depth < len(bucket):
                picked.append(bucket[depth])
                progressed = True
                if len(picked) >= cap:
                    break
        if not progressed:
            break
        depth += 1
    return picked, True


def assign_tail_names(topics: list, tail: list, batch_size: int) -> list:
    """Files the one-off clause names into existing topics, in parallel batches.

    A batch that fails is skipped, not fatal: its names simply stay unfiled, so
    the run loses some evidence weight rather than the whole playbook. Every
    outcome is printed — unfiled names are a silent understatement of evidence
    otherwise, and evidence is what decides which rules reach the playbook.
    """
    valid_ids = {t["topic_id"] for t in topics}
    by_id = {t["topic_id"]: t for t in topics}
    batches = [tail[i:i + batch_size] for i in range(0, len(tail), batch_size)]
    print(f"Filing the {len(tail):,}-name tail into those topics: "
          f"{len(batches)} batch(es) of up to {batch_size}")

    assigned = unfiled = rejected = 0
    failed_batches = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for i, batch in enumerate(batches):
            prompt = assign_prompt(topics, prompt_rows(batch))
            futures[pool.submit(call_structured, prompt, ASSIGN_SCHEMA, "assign_clause_names",
                                call_label="assign")] = (i, batch)
        for fut in as_completed(futures):
            i, batch = futures[fut]
            try:
                result = fut.result()
            except StructuredCallFailed as e:
                failed_batches.append(i)
                print(f"  WARNING: tail batch {i + 1}/{len(batches)} failed, "
                      f"{len(batch)} name(s) left unfiled: {e}")
                continue
            known = {r["clause_name"] for r in batch}
            for a in result.get("assignments", []):
                name, topic_id = a.get("clause_name"), a.get("topic_id") or ""
                # Both guards are load-bearing: a hallucinated topic_id would
                # raise a KeyError later, and a hallucinated clause_name would
                # add a topic member that matches no finding at all.
                if name not in known:
                    rejected += 1
                elif not topic_id:
                    unfiled += 1
                elif topic_id not in valid_ids:
                    rejected += 1
                else:
                    by_id[topic_id].setdefault("matching_clause_names", []).append(name)
                    assigned += 1

    accounted = assigned + unfiled + rejected
    print(f"  {assigned:,} filed, {unfiled:,} left unfiled by the model, "
          f"{rejected:,} rejected as invalid")
    if accounted < len(tail) - sum(len(batches[i]) for i in failed_batches):
        # ASCII on purpose: this goes to a Windows console/log in cp1252, where
        # an em dash lands as a replacement character and makes a real warning
        # look like a corrupted line.
        print(f"  WARNING: {len(tail) - accounted:,} tail name(s) got no answer at all - "
              f"their findings will not count toward any topic's evidence")
    return topics


def body_chars(draft: dict) -> int:
    total = sum(len(draft.get(f, "") or "") for f in CEILINGS)
    total += sum(len(s) for s in draft.get("flag_if", []) or [])
    return total


def _basis_distribution(drafted: list) -> dict:
    """Run-level provenance summary for the methodology page: how many rules
    rest on a preferred position vs an agreed outcome."""
    counts = {}
    for e in drafted:
        key = e.get("comparison_basis") or "unspecified"
        counts[key] = counts.get(key, 0) + 1
    preferred = sum(n for b, n in counts.items()
                    if b in provenance.PREFERRED_POSITION_BASES)
    # Marmon-attributable is the stricter, more honest number for the
    # methodology page: a preferred-position BASIS whose edits we can actually
    # place on our side.
    marmon_attributable = sum(
        1 for e in drafted
        if provenance.is_marmon_preferred_position(e.get("comparison_basis"), e.get("position_side")))
    side_counts = {}
    for e in drafted:
        key = e.get("position_side") or "unspecified"
        side_counts[key] = side_counts.get(key, 0) + 1
    return {"counts": counts, "preferred_position_rules": preferred,
            "marmon_attributable_rules": marmon_attributable,
            "position_sides": side_counts, "total_rules": len(drafted)}


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
    parser.add_argument("--min-evidence-requests", type=int, default=None,
                         help="Absolute alternative to --min-evidence-pct: a topic supported by at "
                              "least this many DISTINCT requests reaches the main playbook even if "
                              "it misses the percentage bar. Matters once the sample is large — "
                              "15%% of 100 contracts is 15, but 15%% of 1,900 is 285, so a pattern "
                              "seen in 200 separate negotiations would be demoted to 'suggested' "
                              "despite being the opposite of the one-off quirk the bar exists to "
                              "catch. Omit to gate on percentage alone.")
    parser.add_argument("--cluster-name-floor", type=int, default=2,
                         help="A clause name needs at least this many findings to take part in the "
                              "topic-forming cluster call; names below it are filed into the "
                              "resulting topics by a second, batched pass instead (their findings "
                              "still count as evidence — see assign_prompt). Exists because the "
                              "cluster call's cost grows with the NAME count in both directions: at "
                              "4,974 names the prompt reached 916k tokens and the service had no "
                              "context left to answer in. Raise it if that call still overflows.")
    parser.add_argument("--max-draft-findings", type=int, default=400,
                         help="Cap on how many of a topic's findings are embedded in its drafting "
                              "prompt (0 for no cap). The prompt carries findings in full, so a "
                              "topic covering most of the population would otherwise build a "
                              "several-hundred-thousand-token prompt and fail. 400 findings spread "
                              "across up to 400 separate contracts is far more evidence than any "
                              "rule in the delivered playbooks was drafted from. Evidence counts, "
                              "percentages and provenance are always computed from ALL of a topic's "
                              "findings, never from this sample — see sample_for_draft.")
    parser.add_argument("--assign-batch-size", type=int, default=300,
                         help="How many one-off clause names each second-pass assignment call "
                              "handles. Batches run in parallel; smaller batches mean more calls "
                              "but each with a smaller prompt and answer.")
    args = parser.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    print(f"Loaded {len(findings)} confirmed findings from {args.findings}")

    usage_dir = Path(__file__).parent / "output" / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    llm_azure.set_usage_log_path(usage_dir / f"playbook_synthesis_{int(time.time())}.jsonl")

    run_start = time.time()

    clustering_rows = cluster_input(findings)
    raw_name_total = len({(f.get("clause_name") or "").strip()
                          for f in findings if (f.get("clause_name") or "").strip()})
    print(f"Distinct clause names: {raw_name_total:,} raw -> {len(clustering_rows):,} after "
          f"normalising typography")

    # PASS 1 clusters only the names that could form a topic on their own; the
    # one-off tail is filed into those topics by PASS 2. See assign_prompt for
    # why this is split rather than done in a single call.
    core = [r for r in clustering_rows if r["finding_count"] >= args.cluster_name_floor]
    tail = [r for r in clustering_rows if r["finding_count"] < args.cluster_name_floor]
    core_findings = sum(r["finding_count"] for r in core)

    findings_json_text = prompt_rows(core)
    # Printed so an overflow is visible BEFORE the call rather than as an opaque
    # failure: this input is what blows up as the population grows.
    print(f"Clustering via Azure OpenAI (model={llm_azure.DEFAULT_MODEL}): "
          f"{len(core):,} names with {args.cluster_name_floor}+ findings "
          f"({core_findings:,}/{len(findings):,} findings, "
          f"{core_findings / len(findings) * 100:.1f}% of evidence), "
          f"~{len(findings_json_text) // 3600:,}k tokens of prompt")
    try:
        # A bigger output cap than the shared default, because this one answer
        # has to echo every clause name back: ~1,100 names is ~15k tokens of
        # pure name before any structure, and high-effort reasoning over a
        # 380k-token input is added to the same budget. The cap costs nothing
        # unused, and the service clamps it to the context left after the input.
        cluster_result = call_structured(cluster_prompt(findings_json_text), CLUSTER_SCHEMA, "cluster_topics",
                                          max_output_tokens=120_000, call_label="cluster")
    except StructuredCallFailed as e:
        raise SystemExit(f"Cluster call failed: {e}")

    topics = cluster_result.get("topics", [])
    print(f"Clustered into {len(topics)} topics")

    if tail and topics:
        topics = assign_tail_names(topics, tail, args.assign_batch_size)

    # Every name the model saw was a display name standing for one or more raw
    # spellings; findings are keyed on the raw spelling, so expand before any
    # evidence is counted.
    topics = expand_to_raw_names(topics, clustering_rows)
    # Counted per RAW spelling, straight from the findings — dedupe weighs a
    # topic by the support of the names only it claims, so giving every spelling
    # its whole group's total would count the same findings once per variant.
    counts = Counter((f.get("clause_name") or "").strip() for f in findings)

    # Enforce one-topic-per-clause-name before any evidence is counted.
    topics, dedupe_report = dedupe_topic_claims(topics, counts)
    if dedupe_report:
        moved = sum(r["findings"] for r in dedupe_report)
        print(f"Resolved {len(dedupe_report)} clause name(s) claimed by more than one topic "
              f"({moved} findings would otherwise have been counted twice):")
        for r in sorted(dedupe_report, key=lambda x: -x["findings"])[:10]:
            print(f"  {r['findings']:>3} findings  {r['clause_name'][:52]!r} -> "
                  f"{r['assigned_to']!r} (removed from {', '.join(repr(t) for t in r['removed_from'])})")
        if len(dedupe_report) > 10:
            print(f"  ... and {len(dedupe_report) - 10} more")

    by_clause_name = {}
    for f in findings:
        by_clause_name.setdefault(f["clause_name"], []).append(f)

    def draft_one(topic):
        matching = [f for name in topic["matching_clause_names"] for f in by_clause_name.get(name, [])]
        evidence_count = len(matching)
        evidence_requests = len({f["request_id"] for f in matching if f.get("request_id") is not None})
        evidence_pct = round(evidence_requests / args.sample_size * 100, 1) if args.sample_size else 0.0
        # Provenance rollup — deterministic arithmetic over this topic's own
        # findings, never an LLM judgement, so the Basis line an attorney reads
        # is reproducible. Per Jeff (2026-08-31): a rule must state whether it
        # represents a preferred starting position or an agreed outcome.
        basis_rollup = provenance.rollup(
            [f.get("comparison_basis") for f in matching if f.get("comparison_basis")])
        contributing_authors = sorted({
            a for f in matching for a in (f.get("edit_authors") or [])
            if a and a != "unattributed"})
        # WHOSE position this rule represents (annotate_finding_sides.py stamps
        # position_side per finding). Kept separate from the comparison basis
        # because a redline basis alone does not make the edits Marmon's — one
        # request in the live subset was the counterparty's redline of our
        # draft. dominant_side() refuses to pick a winner when both sides'
        # edits support the same rule.
        sides = [f.get("position_side") for f in matching if f.get("position_side")]
        side = provenance.dominant_side(sides)
        side_counts = {}
        for s in sides:
            side_counts[s] = side_counts.get(s, 0) + 1
        shown, sampled = sample_for_draft(matching, args.max_draft_findings)
        if sampled:
            print(f"  {topic['topic_id']}: showing {len(shown)} of {len(matching)} findings "
                  f"(spread across {len({f.get('request_id') for f in shown})} requests); "
                  f"evidence stats still counted from all {len(matching)}")
        prompt = draft_prompt(topic, shown, evidence_total=len(matching))
        try:
            draft = None
            # Escalating the cap is a DIFFERENT call, not a retry of the same
            # one — which is why it is allowed here even though
            # NonRetryableCallFailed exists to stop identical retries. Measured
            # on the 2026-09-01 population run: topic RST-02 used exactly 45,000
            # of 45,000 output tokens against only 74,790 input, so it was
            # genuinely writing (mostly reasoning) rather than being crowded out
            # by its prompt, and ~800k of context sat unused. One topic silently
            # missing from a playbook is worse than one extra call.
            for cap in DRAFT_OUTPUT_CAPS:
                try:
                    draft = call_structured(prompt, DRAFT_SCHEMA, "draft_rule",
                                             max_output_tokens=cap,
                                             call_label=f"draft:{topic['topic_id']}")
                    break
                except NonRetryableCallFailed:
                    if cap == DRAFT_OUTPUT_CAPS[-1]:
                        raise
                    print(f"  {topic['topic_id']}: exhausted a {cap:,}-token output cap, "
                          f"retrying at {DRAFT_OUTPUT_CAPS[DRAFT_OUTPUT_CAPS.index(cap) + 1]:,}")
            return {
                "topic": topic, "draft": draft,
                "evidence_count": evidence_count, "evidence_requests": evidence_requests,
                "evidence_pct": evidence_pct,
                "comparison_basis": basis_rollup["dominant"],
                "comparison_basis_label": provenance.label(basis_rollup["dominant"]),
                "position_side": side,
                "position_label": provenance.position_label(basis_rollup["dominant"], side),
                "position_side_counts": side_counts,
                "basis_summary": basis_rollup["summary"],
                "basis_counts": basis_rollup["counts"],
                "preferred_position_count": basis_rollup["preferred_position_count"],
                "contributing_authors": contributing_authors,
            }
        except StructuredCallFailed as e:
            print(f"  Topic {topic['topic_id']} ({topic['title']}): draft call failed ({e}) - excluded")
            return {"topic": topic, "draft": None, "error": str(e),
                     "evidence_count": evidence_count, "evidence_requests": evidence_requests,
                     "evidence_pct": evidence_pct}

    print("Drafting rules...")
    drafted, failed_topics = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(draft_one, t) for t in topics]
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result and result.get("draft"):
                drafted.append(result)
            elif result:
                failed_topics.append(result)
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

    # Percentage OR absolute count. Tiering runs AFTER every topic is drafted,
    # so changing either bar is free — no topic is ever left undrafted because
    # of where the line sits, only routed to a different tier.
    def qualifies(e):
        if e["evidence_pct"] >= args.min_evidence_pct:
            return True
        return (args.min_evidence_requests is not None
                and e["evidence_requests"] >= args.min_evidence_requests)

    confirmed_tier = [e for e in drafted if qualifies(e)]
    suggested_tier = [e for e in drafted if not qualifies(e)]
    on_absolute_only = [e for e in confirmed_tier if e["evidence_pct"] < args.min_evidence_pct]

    print(f"\nDone: {len(drafted)}/{len(topics)} topics drafted into rules")
    print(f"  {len(confirmed_tier)} meet the {args.min_evidence_pct}% evidence bar"
          + (f" or the {args.min_evidence_requests}-request floor" if args.min_evidence_requests else "")
          + " -> main playbook")
    if on_absolute_only:
        print(f"    of those, {len(on_absolute_only)} qualified on the absolute floor alone: "
              + ", ".join(f"{e['evidence_requests']} requests ({e['evidence_pct']}%)"
                          for e in sorted(on_absolute_only,
                                          key=lambda x: -x["evidence_requests"])[:6]))
    print(f"  {len(suggested_tier)} below the bar (but 2+ findings) -> suggested rules")
    # The distribution, so the bar can be chosen from the data rather than
    # guessed — and so a bar that admits almost nothing is visible immediately.
    if drafted:
        by_req = sorted((e["evidence_requests"] for e in drafted), reverse=True)
        print(f"  evidence spread (distinct requests per topic): max {by_req[0]}, "
              f"median {by_req[len(by_req) // 2]}, min {by_req[-1]}")
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
            # Provenance, per Jeff (2026-08-31): every rule states whether it
            # represents a pre-compromise Marmon position or an agreed outcome,
            # so a reader never has to guess which kind of guidance it is.
            "comparison_basis": e.get("comparison_basis"),
            "comparison_basis_label": e.get("comparison_basis_label"),
            "position_side": e.get("position_side"),
            "position_label": e.get("position_label"),
            "position_side_counts": e.get("position_side_counts"),
            "basis_summary": e.get("basis_summary"),
            "basis_counts": e.get("basis_counts"),
            "preferred_position_count": e.get("preferred_position_count"),
            "contributing_authors": e.get("contributing_authors"),
        }

    output = {
        "result": {
            "topicsTotal": len(topics),
            "rulesDrafted": len(drafted),
            "sampleSize": args.sample_size,
            "minEvidencePct": args.min_evidence_pct,
            "minEvidenceRequests": args.min_evidence_requests,
            "avgRuleBodyChars": avg_body,
            "fieldsOverCeiling": over_ceiling,
            "basisDistribution": _basis_distribution(drafted),
            # A topic that clustered but failed to draft is a HOLE in the
            # playbook, and rulesDrafted < topicsTotal is the only trace of it
            # otherwise — a number nobody reads, with the topic's identity left
            # in a log file. Naming them here means the gap travels with the
            # data: finalize/validate and anyone reading the raw result can see
            # exactly which negotiating issue is missing and how much evidence
            # it had.
            "failedTopics": [{
                "topic_id": e["topic"].get("topic_id"),
                "title": e["topic"].get("title"),
                "category": e["topic"].get("category"),
                "evidence_count": e["evidence_count"],
                "evidence_requests": e["evidence_requests"],
                "evidence_pct": e["evidence_pct"],
                "error": e["error"],
            } for e in failed_topics],
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
