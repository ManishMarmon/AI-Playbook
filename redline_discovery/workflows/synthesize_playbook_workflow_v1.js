// ARCHIVED v1 — superseded by synthesize_playbook_workflow.js. Kept for
// comparison/reproducibility only; do not run this for new playbooks.
//
// Why it was replaced: measured against the reference Freo Group AU playbook,
// v1's rules averaged ~5,040 characters vs. Freo's ~1,057 (required field 8x
// longer, escalate_if 5x, preferred_language 4x). The cause was in this
// file's draft prompt: asking for conservatism and pattern-grounding across
// all findings pushed the model to show its reasoning inside the rule fields
// (hedges, enumerations, parentheticals) instead of stating a decided
// position the way a lawyer-authored playbook does. v1 output is preserved at
// mclegal-frontend/public/playbooks/real-estate-usa-v1.json.
//
// Turns Phase 5 clause-tagging output (many contracts' worth of real
// draft-vs-signed clause changes) into a first-draft Golden Rules playbook,
// in the same schema as the human-authored Freo Group AU playbook. This is
// the actual "build a rulebook from understanding what changed in real
// negotiations" step — Freo's document is the target SHAPE, not something
// this pipeline depends on existing for a new contract type.
//
// Invoke with args: { findingsPath: "<repo>/redline_discovery/output/<x>_clause_findings.json" }
// — findingsPath is a JSON array of CONFIRMED findings (already verified
// accurate by Phase 5's adversarial check): clause_name, before_text,
// after_text, change_type, spirit_before, spirit_after, negotiation_intent,
// significance, request_id, vendor, request_title.
//
// Every rule this produces is explicitly source_tag: "Unvetted draft -
// counsel review needed" (same literal tag Freo's own playbook uses for its
// AI-unvetted clauses) — nothing here has been seen by a lawyer. The
// frontend's isUnvetted() check keys off that exact substring.

export const meta = {
  name: 'synthesize-playbook-v1-archived',
  description: 'ARCHIVED v1 — verbose-output synthesis, superseded by synthesize-playbook',
  phases: [
    { title: 'Cluster', detail: 'group findings into clause topics + categories' },
    { title: 'Draft', detail: 'per-topic LLM drafts one rule from the pattern across all its findings' },
  ],
}

const CLUSTER_SCHEMA = {
  type: 'object',
  properties: {
    topics: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          topic_id: { type: 'string' },
          title: { type: 'string' },
          category: { type: 'string' },
          category_prefix: { type: 'string' },
          matching_clause_names: { type: 'array', items: { type: 'string' } },
        },
        required: ['topic_id', 'title', 'category', 'category_prefix', 'matching_clause_names'],
      },
    },
  },
  required: ['topics'],
}

const DRAFT_SCHEMA = {
  type: 'object',
  properties: {
    title: { type: 'string' },
    priority: { type: 'string', enum: ['MUST PRESS', 'PRESS', 'MANAGE', 'ACCEPT+NOTE'] },
    applies_to: { type: 'string' },
    where_to_look: { type: 'string' },
    required: { type: 'string' },
    fallback: { type: 'string' },
    escalate_if: { type: 'string' },
    flag_if: { type: 'array', items: { type: 'string' } },
    preferred_language: { type: 'string' },
    confidence_note: { type: 'string' },
  },
  required: ['title', 'priority', 'applies_to', 'where_to_look', 'required', 'fallback', 'escalate_if', 'flag_if', 'preferred_language', 'confidence_note'],
}

let rawArgs = args
if (typeof rawArgs === 'string') rawArgs = JSON.parse(rawArgs)
const findingsPath = rawArgs.findingsPath

function clusterPrompt() {
  return `Read the JSON file at "${findingsPath}". It's an array of VERIFIED, real clause-level findings from actual contract negotiations — each shows a clause_name, what the clause said before negotiation vs. after (spirit_before/spirit_after), why it was likely changed (negotiation_intent), and how significant the change was.

The clause_name field was assigned per-finding by an earlier pass and is NOT already normalized — near-duplicate wording will exist (e.g. "Return of Confidential Information" vs "Return/Destruction of Materials" vs "Return of Documents on Termination" may all be the same underlying negotiating topic).

Your job: read through ALL findings and group them into a set of distinct RULE TOPICS — one topic per genuinely distinct negotiating issue a contracts attorney would treat as its own checklist item. Merge near-duplicate clause_name variants into one topic; keep genuinely different issues separate even if superficially similar (e.g. "assignment by tenant" and "subletting by tenant" are related but usually distinct topics).

For each topic, also assign it to a CATEGORY — a broader risk-area grouping (the same idea as how a playbook might group topics under headings like "Liability & Indemnity", "Payment & Money", "Term & Termination" — but invent categories that actually fit what's in THIS data; do not force real-estate-specific findings into categories that don't fit, and do not assume in advance what categories should exist). Aim for roughly 6-12 categories total, each covering several topics.

Only create a topic for something that appears in at least 2 findings (ideally more) — a single one-off finding usually isn't a stable enough pattern to build a rule from; skip it rather than inventing a topic around one data point. Every finding's clause_name should map to at most one topic's matching_clause_names list.

Also assign each CATEGORY (not each topic) a short rule-id prefix, 2-4 uppercase letters, e.g. "LIA" for "Liability & Indemnity" or "PAY" for "Payment & Money" — this becomes part of every rule's id in that category (e.g. LIA-01), so every category's prefix must be distinct from every other category's prefix in this same response. Repeat the same category_prefix on every topic that shares a category.`
}

function draftPrompt(topic, findingsSummary) {
  return `You are drafting ONE rule for a Golden Rules contract-review playbook, in the same style as an attorney-authored playbook (fields: priority, applies_to, where_to_look, required, fallback, escalate_if, flag_if, preferred_language).

This rule covers the topic "${topic.title}" (category: ${topic.category}). Read the JSON file at "${findingsPath}" and look specifically at the findings whose clause_name is one of: ${JSON.stringify(topic.matching_clause_names)}. Ignore all other findings in the file — they belong to different topics.

${findingsSummary}

Each finding shows a REAL negotiated change: what a clause said before negotiation (spirit_before) vs. after (spirit_after), across a real contract between a Marmon business unit and a real counterparty. Treat "before" as roughly what counterparties/their counsel tend to propose, and "after" (the negotiated/signed position) as roughly where Marmon's side has actually been landing this issue in practice.

Synthesize ONE rule from the PATTERN across all of this topic's findings (not any single instance):
- priority: MUST PRESS if the findings show this is consistently contested and high-stakes (significance mostly "high", the position moves substantially); PRESS if real but more moderate; MANAGE if it's a real issue but lower-stakes or inconsistently pushed; ACCEPT+NOTE if it's usually just noted/accepted rather than fought over.
- applies_to: this field is matched EXACTLY by downstream code, so it must be either the literal string "All contract types", or a short specific sub-type name under 40 characters (e.g. "Ground lease", "Purchase agreement") if — and only if — the findings clearly show this rule doesn't apply to every deal this playbook covers. Do NOT write a descriptive sentence or parenthetical here (that belongs in where_to_look or confidence_note instead) — an exact-match value is required for the rule to ever actually get selected.
- where_to_look: where in a real estate contract this issue typically shows up (section/clause type).
- required: the strongest defensible position Marmon should ask for first — informed by the best-observed "after" positions across the findings, not just the average.
- fallback: a realistic fallback position — where negotiations have actually landed most often across the findings, when "required" isn't achievable.
- escalate_if: conditions under which this should never be accepted / must go to an attorney regardless of how negotiations are going — informed by the worst "before" positions seen, if any are genuinely dangerous.
- flag_if: an array of concrete textual/contextual signals a reviewer should watch for that indicate this rule may be violated.
- preferred_language: draft realistic contract clause language implementing the REQUIRED position, in plain professional contract-drafting style. This is a first draft only, not reviewed by counsel.
- confidence_note: one honest sentence on how many findings this is based on and how consistent the pattern was (e.g. "Based on 4 findings across 4 different counterparties, consistent direction" vs "Based on 2 findings with mixed signals — treat this rule as especially provisional").

Be conservative: if the findings for this topic are sparse or inconsistent, say so plainly in confidence_note and lean toward a lower priority (MANAGE) rather than overclaiming MUST PRESS from thin evidence.`
}

phase('Cluster')
const clusterResult = await agent(clusterPrompt(), { schema: CLUSTER_SCHEMA, phase: 'Cluster', label: 'cluster-topics' })
const topics = (clusterResult && clusterResult.topics) || []
log(`Clustered into ${topics.length} topics`)

phase('Draft')
const drafted = await pipeline(
  topics,
  (topic) => agent(
    draftPrompt(topic, `This topic currently matches ${topic.matching_clause_names.length} distinct clause-name variant(s).`),
    { schema: DRAFT_SCHEMA, phase: 'Draft', label: `draft:${topic.topic_id}` }
  ),
  (draftResult, topic) => {
    if (!draftResult) {
      log(`Topic ${topic.topic_id} (${topic.title}): draft call failed — excluded`)
      return null
    }
    return { topic, draft: draftResult }
  }
)

const succeeded = drafted.filter(Boolean)
log(`Done: ${succeeded.length}/${topics.length} topics drafted into rules`)

return {
  topicsTotal: topics.length,
  rulesDrafted: succeeded.length,
  rules: succeeded.map(({ topic, draft }) => ({
    title: draft.title,
    category: topic.category,
    category_prefix: topic.category_prefix,
    priority: draft.priority,
    applies_to: draft.applies_to,
    where_to_look: draft.where_to_look,
    required: draft.required,
    fallback: draft.fallback,
    escalate_if: draft.escalate_if,
    flag_if: draft.flag_if,
    preferred_language: draft.preferred_language,
    source_tag: 'Unvetted draft - counsel review needed',
    confidence_note: draft.confidence_note,
    matching_clause_names: topic.matching_clause_names,
  })),
}
