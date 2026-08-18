// Phase 5 (AI Understanding) pipeline. Not a standalone Node script — this
// runs via Claude Code's Workflow tool, which supplies agent()/pipeline()/
// parallel()/phase()/log()/args at execution time.
//
// Invoke with args: { chunkDir: "<repo>/redline_discovery/output/diff_chunks",
// requestIds: [...] } — one JSON file per request id, produced by run_pairing.py.

export const meta = {
  name: 'redline-clause-tagging',
  description: 'Merge raw diff fragments into clause-level negotiated edits and adversarially verify each finding against source text',
  phases: [
    { title: 'Tag', detail: 'per-request LLM merges raw diff opcodes into clause-level findings' },
    { title: 'Verify', detail: 'independent adversarial check of each high/medium finding against raw source' },
  ],
}

const TAG_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          clause_name: { type: 'string' },
          location: { type: 'string' },
          before_text: { type: 'string' },
          after_text: { type: 'string' },
          change_type: { type: 'string', enum: ['insertion', 'deletion', 'modification'] },
          spirit_before: { type: 'string' },
          spirit_after: { type: 'string' },
          negotiation_intent: { type: 'string' },
          significance: { type: 'string', enum: ['high', 'medium', 'low', 'noise'] },
          source_edit_indices: { type: 'array', items: { type: 'integer' } },
        },
        required: ['clause_name', 'before_text', 'after_text', 'change_type', 'spirit_before', 'spirit_after', 'significance', 'source_edit_indices'],
      },
    },
  },
  required: ['findings'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    accurate: { type: 'boolean' },
    issue: { type: 'string' },
    corrected_clause_name: { type: 'string' },
  },
  required: ['accurate', 'issue'],
}

let rawArgs = args
if (typeof rawArgs === 'string') rawArgs = JSON.parse(rawArgs)
const chunkDir = rawArgs.chunkDir
let requestIds = rawArgs.requestIds
if (typeof requestIds === 'string') requestIds = JSON.parse(requestIds)
log(`args resolved: chunkDir=${chunkDir}, requestIds is array=${Array.isArray(requestIds)}, count=${Array.isArray(requestIds) ? requestIds.length : 'n/a'}`)

function tagPrompt(rid) {
  return `Read the JSON file at "${chunkDir}/${rid}.json". It contains one CobbleStone contract negotiation request with fields: request_title, requestor, vendor, original_file, redline_file, and an "edits" array — raw word-level diff opcodes (type: insert/delete/replace, before, after, context_before, context_after) comparing the ORIGINAL submitted contract file's text against the REDLINED/reviewed copy's text.

These raw edits are fragmented — a single sentence-level negotiated change is often split across several adjacent opcodes (e.g. a replace immediately followed by an insert, or several small replaces in a row within the same sentence). Your job: read through the edits array IN ORDER along with their context_before/context_after, and MERGE adjacent/related fragments into coherent clause-level findings — one finding per actual substantive change a contracts negotiator would care about, not one per raw diff opcode.

For every real change (do not invent changes that aren't there), produce a finding with:
- clause_name: the specific named clause this belongs to (e.g. "Permitted Disclosure", "Limitation of Liability", "Indemnification", "Governing Law", "Term and Termination", "Preamble" for opening/party-identification language). Infer from context_before/context_after — the surrounding text usually reveals the clause even without an explicit heading.
- location: whatever location detail you can infer (section number, clause heading, "first paragraph of Preamble", etc.) — best-effort, empty string if truly unknown.
- before_text / after_text: the ACTUAL original wording and ACTUAL new wording, quoted directly from the before/after/context fields of the source edits — do not paraphrase these two fields, only quote/reconstruct from what's literally in the raw edits. after_text empty string for a pure deletion, before_text empty string for a pure insertion.
- change_type: "insertion", "deletion", or "modification"
- spirit_before / spirit_after: one plain-English sentence each describing what the language meant/required before vs. what it means/requires now
- negotiation_intent: one sentence on why a party likely wanted this change
- significance: "high" (substantive legal/commercial change — allocates risk, changes an obligation, changes scope/parties/money/liability), "medium" (a real but narrower substantive change), "low" (trivial wording/style change with no practical effect), or "noise" (not a real change at all — PDF text-extraction artifact, mangled character spacing like "r e a s o n a b l y", pure whitespace/paragraph-reflow, duplicate boilerplate)
- source_edit_indices: array of the 0-based indices into the edits array that this finding was built from

Be conservative about "noise" — only use it for genuine extraction garbage, not just because a change looks minor (minor real changes are "low", not "noise"). Skip pure reformatting entirely (don't report a finding for it at all, not even as noise) if it's obviously just line-wrap/whitespace with literally no textual difference in meaning. Do not report more than one finding for the same underlying change — merge, don't duplicate.`
}

function verifyPrompt(rid, finding) {
  return `You are adversarially checking one AI-extracted "clause edit" finding from a contract redline, for accuracy. Your job is to catch hallucination or mischaracterization — default to skeptical, not to agreeing.

Read the JSON file at "${chunkDir}/${rid}.json" and look at the edits array at these indices: ${JSON.stringify(finding.source_edit_indices)}. Those raw diff fragments (before/after/context_before/context_after) are the ONLY source of truth for whether this finding is accurate.

CLAIMED FINDING (produced by another AI pass, to be checked — not trusted):
- clause_name: ${finding.clause_name}
- location: ${finding.location}
- before_text (claimed quote): "${finding.before_text}"
- after_text (claimed quote): "${finding.after_text}"
- change_type: ${finding.change_type}
- spirit_before: ${finding.spirit_before}
- spirit_after: ${finding.spirit_after}
- negotiation_intent: ${finding.negotiation_intent}
- significance: ${finding.significance}

Check, against the raw edits at the given indices:
1. Are before_text/after_text genuinely supported by (present in, or a faithful close paraphrase of) the raw before/after/context fields at those indices? Flag if fabricated, if pulled from the wrong indices, or if it materially misquotes the source.
2. Is clause_name plausible given the raw text and its context_before/context_after — not necessarily provably certain, but not clearly wrong or contradicted by the context either?
3. Do spirit_before/spirit_after/negotiation_intent overclaim — read legal/business meaning into the change that the actual text doesn't support?

Set accurate=false if you are uncertain whether the quoted text is genuinely supported by the raw source at those indices — only accurate=true if the quotes and characterization clearly hold up under your check. If accurate=false because of a wrong-but-fixable clause name, put the correct one in corrected_clause_name (empty string otherwise). Explain the problem in "issue" (empty string if accurate=true).`
}

phase('Tag')
const results = await pipeline(
  requestIds,
  (rid) => agent(tagPrompt(rid), { schema: TAG_SCHEMA, phase: 'Tag', label: `tag:${rid}` }),
  async (tagResult, rid) => {
    const findings = (tagResult && tagResult.findings) || []
    const toVerify = findings.filter(f => f.significance === 'high' || f.significance === 'medium')
    const lowOrNoise = findings.filter(f => f.significance !== 'high' && f.significance !== 'medium')

    const verified = await parallel(toVerify.map(f => () =>
      agent(verifyPrompt(rid, f), { schema: VERIFY_SCHEMA, phase: 'Verify', label: `verify:${rid}` })
        .then(v => ({ ...f, request_id: rid, verification: v }))
    ))

    log(`Request ${rid}: ${findings.length} findings tagged, ${toVerify.length} verified`)
    return {
      request_id: rid,
      verified_findings: verified.filter(Boolean),
      low_or_noise_findings: lowOrNoise.map(f => ({ ...f, request_id: rid })),
    }
  }
)

const clean = results.filter(Boolean)
const confirmed = clean.flatMap(r => r.verified_findings.filter(f => f.verification && f.verification.accurate))
const flagged = clean.flatMap(r => r.verified_findings.filter(f => f.verification && !f.verification.accurate))
const lowOrNoise = clean.flatMap(r => r.low_or_noise_findings)

log(`Done: ${clean.length}/${requestIds.length} requests tagged, ${confirmed.length} confirmed findings, ${flagged.length} flagged inaccurate, ${lowOrNoise.length} low/noise (not verified)`)

return { confirmed, flagged, lowOrNoise, requestsProcessed: clean.length, requestsTotal: requestIds.length }
