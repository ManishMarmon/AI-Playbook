# AI Playbook — Marmon Contract Intelligence

An AI system built on top of Marmon's CobbleStone/Mpact contract-request data that does three related
things, in increasing order of ambition:

1. **Redline discovery** — find and understand what actually changed between a draft contract and its
   signed version, across real negotiation history.
2. **Golden Rules review** — check a specific contract against an attorney-authored playbook (a set of
   "required position / fallback / escalate if" rules) and report violations.
3. **Playbook synthesis** — the actual end goal of this project: *build* a Golden-Rules-style playbook
   from scratch for a given contract type + jurisdiction, by mining what real negotiations show Marmon
   consistently pushes for and settles at, rather than requiring a human to author one first.

A human-authored example (Freo Group AU's crane-hire playbook) exists and is used as the **target
schema/format**, not as a precondition — every new playbook this project produces is meant to stand on
its own, built from real draft-vs-signed contract pairs for that contract type/jurisdiction.

- **Repo:** https://github.com/ManishMarmon/AI-Playbook (branch `main`)
- **Backend:** `redline_discovery/` (Python + a few JS files run through Claude Code's Workflow tool)
- **Frontend:** `mclegal-frontend/` (React + Vite + TypeScript, no backend server — reads static JSON)
- **Data:** local Postgres (`aiplaybook` database) holds the full CobbleStone extract; the frontend reads
  pre-generated JSON snapshots written by the Python scripts, not Postgres directly.

## How the pieces fit together

```
                         ┌─────────────────────────────────────────┐
                         │            Postgres (aiplaybook)          │
                         │   requests, files — full CobbleStone      │
                         │   extract, kept current by backfill/sync  │
                         └───────────────┬───────────────────────────┘
                                          │  db.get_requests() / get_files_for_request()
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
             run_discovery.py       run_pairing.py         run_review.py
             (Phases 1-3)           (Phase 4)              (B2 candidate selection)
             find + classify        pair draft vs signed,  pick which playbook + file
             redlines                word-diff them         applies to a request
                    │                     │                     │
                    ▼                     ▼                     ▼
         clause_tagging_workflow.js  diff_chunks/*.json   golden_rules_review_workflow.js
         (Phase 5, LLM)              per-request diffs    (B2, LLM) — evaluate every rule
         tag + verify each clause                          against the request's text
         change as a "finding"              │                     │
                    │                       │                     ▼
                    │                       │              finalize_review.py
                    │                       │              → golden_rules_findings.json
                    │                       │
                    ▼                       │
       extract_confirmed_findings.py        │
                    │                       │
                    ▼                       │
       synthesize_playbook_workflow.js  ◄───┘  (reads the SAME diff/finding data,
       (LLM) — cluster findings into            for a different purpose: not "check
       topics, draft one rule per topic          this contract" but "what does the
                    │                            pattern across many contracts imply
                    ▼                            the rule should be?")
          finalize_playbook.py
          → <playbook-id>.json + manifest.json entry
                    │
                    ▼
       mclegal-frontend: Playbooks.tsx (browse/preview/download as Word)
                         DraftContract.tsx (jurisdiction + contract type → first-draft PDF)
                         GoldenRules.tsx (B2 violations dashboard)
```

The **same underlying data** (real draft-vs-signed clause changes) feeds two different consumers:
B2 asks "does THIS contract violate an EXISTING playbook rule?"; playbook synthesis asks "what SHOULD
the rule be, given the pattern across MANY contracts?" They share Phase 4/5 but diverge after that.

## Repository layout

```
redline_discovery/              Backend pipeline (Python), run manually per stage
  config.py                     CobbleStone/Mpact API + Postgres config (Key Vault + .env, see below)
  request_api.py                CobbleStone API client (auth, pagination, file download)
  db.py                         Postgres data-access layer (see "Data layer" below)
  db/schema.sql, db/setup.sql   One-time DB setup (run manually in pgAdmin)
  backfill.py                   One-time full extraction: all CobbleStone requests/files → Postgres
  sync_updates.py               Ongoing incremental sync (new + changed requests, active-request files)
  fetch_snapshot.py             Optional: dump a JSON snapshot instead of reading Postgres (ad-hoc/manual)

  classifier.py                 Phase 1-3: filename/text/email keyword heuristics
  structure_check.py            Phase 3: real Word track-changes / PDF-annotation detection on file bytes
  run_discovery.py              Phase 1-3 entry point — discovers and classifies redlines
  pairing.py                    Phase 4: pairs a redline file against its original
  diffing.py                    Phase 4: word-level diff between original and redline text
  run_pairing.py                Phase 4 entry point — pair + diff a batch (filterable by
                                 --request-type/--geography — this is how a playbook's source
                                 population gets scoped, e.g. "Real Estate" + "U.S.")

  build_request_meta.py         Looks up request_title/party_a/party_b in Postgres for every
                                 request id run_pairing.py produced a diff chunk for — feeds
                                 clause_tagging_workflow.js's requestMeta arg
  extract_confirmed_findings.py  Pulls the CONFIRMED findings array out of a saved
                                 clause_tagging_workflow.js run, for synthesis to consume
  finalize_playbook.py          Turns a synthesize_playbook_workflow.js result into a real
                                 playbook JSON + manifest.json entry (rule-id assignment,
                                 cross-playbook collision checks, applies_to sanity checks)
  playbook_parser.py            Parses a HUMAN-AUTHORED playbook .docx (e.g. Freo Group AU) into
                                 the same JSON shape — used once, to seed the reference playbook

  review_selection.py           B2: pure logic — which playbook governs a request, which file
                                 is its "current state" to check
  run_review.py                 B2 entry point — builds review candidates (no LLM call itself)
  finalize_review.py            B2: turns the raw review workflow result into the dashboard's
                                 golden_rules_findings.json (attaches preferred_language verbatim,
                                 never round-tripped through the LLM)

  run_analytics.py              Phase 6: aggregates Phase 1-5 outputs into dashboard metrics

  workflows/                    Run via Claude Code's Workflow tool, NOT standalone Node —
                                 each expects `args` supplied by the tool invocation
    clause_tagging_workflow.js       Phase 5 — tag + adversarially verify clause-level findings
    ai_classification_workflow.js    Phase 3 fallback — LLM judgment on ambiguous attachments
    golden_rules_review_workflow.js  B2 — evaluate a contract against every rule in its playbook
    synthesize_playbook_workflow.js  Playbook synthesis — cluster findings into topics, draft rules
    synthesize_playbook_workflow_v1.js  Archived — superseded by the tightened version above;
                                 kept to show why (see "Playbook synthesis" below)

mclegal-frontend/                Dashboard + tools (React + Vite), no backend server
  src/pages/
    Discovery.tsx                Phase 1-3 results, per-request redline classification
    RedlineDiffs.tsx             Phase 4 results, word-level diffs
    ClauseFindings.tsx           Phase 5 results, verified clause-level findings
    GoldenRules.tsx              B2 results — violations / flagged / satisfied / n/a, by rule priority
    Requests.tsx                 Browse all CobbleStone request metadata, cascading filters
    Playbooks.tsx                Browse/preview/download-as-Word every playbook (human or AI-drafted)
    DraftContract.tsx            Pick jurisdiction + contract type → auto-resolve playbook →
                                 first-draft contract PDF (Party A/B + anything else mandatory)
    Analytics.tsx                Phase 6 aggregate metrics
  src/lib/
    contractAssembly.ts          Orders a playbook's rules into a conventional contract structure
    renderContractPdf.ts         Client-side PDF assembly (jsPDF) for DraftContract.tsx
    renderPlaybookDocx.ts        Client-side Word export (docx) for Playbooks.tsx — reproduces the
                                 reference Freo document's exact structure/styling
    playbooks.ts                 Shared PlaybookMeta type + manifest type guard

  public/playbooks/manifest.json + <id>.json   Committed to git — parsed/synthesized playbook
                                 content is stable business output, not a live-API snapshot
  public/data/*.json             NOT committed (gitignored) — regenerated output from the Python
                                 scripts; copy from redline_discovery/output/ after running the pipeline
```

## Data layer: Postgres, not a JSON snapshot

CobbleStone holds ~19,700+ requests — too many to re-fetch from the live API on every pipeline run.
`db.py` is the single data-access layer every script goes through:

- **`requests`/`files` tables** each store the complete original CobbleStone record in a `raw JSONB`
  column, plus first-class columns for only the fields actually filtered/indexed (contract type,
  geography, business sector, process status, dates, law firm, attorney, parties, ...). Nothing
  CobbleStone returns is ever lost; adding a new first-class column later is an `ALTER TABLE` + backfill
  from `raw`, never a re-fetch from the API.
- **`backfill.py`** does the one-time full extraction. It's resumable by construction — it just continues
  from `MAX(request_id)` already in the table, commits after each request, and upserts are idempotent
  (`ON CONFLICT DO UPDATE`), so killing and re-running it is always safe.
- **`sync_updates.py`** keeps it current afterward: new requests, requests whose `DateUpdated` changed,
  and a file-list refresh for still-active requests only (terminal-status requests aren't re-checked).
  Not yet scheduled — run manually.
- `run_discovery.py`/`run_pairing.py`/`run_review.py` all read via `db.get_requests(...)`, which
  reconstructs dicts shaped **identically** to CobbleStone's own API response — the actual pipeline logic
  in `pairing.py`, `classifier.py`, `structure_check.py`, `review_selection.py` never needed to change
  when the data source moved from live API → JSON snapshot → Postgres.

Connection settings live in a gitignored `.env` (`.env.example` documents the shape); `config.py` loads
them lazily the same way it lazily loads Mpact/CobbleStone OAuth credentials from Azure Key Vault.

## Running the pipeline

```bash
python -m venv venv
venv/Scripts/activate            # source venv/bin/activate on macOS/Linux
pip install -r redline_discovery/requirements.txt
cd redline_discovery
```

**Redline discovery (Phases 1-5):**
```bash
python run_discovery.py --limit 200                            # Phases 1-3: discover + classify
python run_pairing.py --limit 200                               # Phase 4: pair + diff
# Phase 5 (clause_tagging_workflow.js) is invoked through Claude Code's Workflow tool:
#   args: { chunkDir: "output/diff_chunks", requestIds: [...] }
python run_analytics.py                                          # Phase 6: aggregate metrics
```

**B2 — check a contract against an existing playbook:**
```bash
python run_review.py --limit 200
# workflows/golden_rules_review_workflow.js via the Workflow tool, args per its own header comment
python finalize_review.py --raw <saved workflow output> --copy-to-frontend
```

**Playbook synthesis — build a NEW playbook for a contract type + jurisdiction:**
```bash
python run_pairing.py --limit 500 --request-type "Equipment Leasing" --geography "U.S."
python build_request_meta.py --chunk-dir output/diff_chunks --out output/<name>_request_meta.json
# Phase 5 tagging via the Workflow tool: args: { chunkDir, requestIds, requestMeta } —
# requestIds/requestMeta come from the diff_chunks directory and the file above
python extract_confirmed_findings.py --raw <saved tagging output> --out output/<name>_clause_findings.json
# synthesize_playbook_workflow.js via the Workflow tool:
#   args: { findingsPath: "output/<name>_clause_findings.json" }
python finalize_playbook.py --raw <saved synthesis output> \
    --id equipment-leasing-usa --label "US Equipment Leasing" \
    --jurisdiction "United States" --contract-types "Equipment Leasing" \
    --prefix-namespace EL
```
`--prefix-namespace` keeps this playbook's auto-generated rule-id prefixes (e.g. `DOC`, `TRM`) from
colliding with another playbook's prefixes — each synthesis run only sees its own categories, so
`finalize_playbook.py` also hard-fails on any cross-playbook `rule_id` collision it detects, rather than
silently overwriting one playbook's rule with another's id.

Every synthesized rule is stamped `source_tag: "Unvetted draft - counsel review needed"` and the
manifest entry gets `status: "ai_draft"` — nothing produced this way has been seen by a lawyer.
`applies_to` is matched **exactly** by `contractAssembly.ts`; `finalize_playbook.py` warns on any rule
whose `applies_to` looks like prose instead of a short exact-match value, since that silently drops the
rule from every drafted contract.

## Running the dashboard

```bash
cd mclegal-frontend
npm install
npm run dev
```

Most pages read from `public/data/*.json` (gitignored — copy from `redline_discovery/output/` after
running the pipeline). The Playbooks and Draft Contract pages read from `public/playbooks/` (committed —
stable business content, not a live snapshot).

## Playbook synthesis: quality lessons worth knowing before adding a new contract type

- **`synthesize_playbook_workflow_v1.js` is kept, not deleted.** Its first output (Real Estate v1)
  averaged ~5,040 characters of rule body per rule — 4.8x the reference Freo document's ~1,057 — because
  the drafting prompt let the model reason and hedge inside the rule fields themselves. The current
  workflow's prompt explicitly forbids that ("state conclusions, don't show your work in a rule field";
  uncertainty is expressed by choosing a lower priority and saying so in `confidence_note`, never by
  qualifying the rule text) and enforces per-field length ceilings, self-measured and logged at the end
  of every run. Real Estate v2 landed at ~1,653 chars/rule (1.6x Freo) — regenerate any future playbook
  through the current workflow, not the archived v1.
- **Only build a topic/rule from a real pattern.** The cluster prompt explicitly skips any topic backed
  by fewer than ~2 findings — a one-off clause change isn't a stable enough signal to draft a rule from.
- **Not every small contract-type population produces usable pairs.** "Right of Entry" (smallest
  population at the time) was tried and abandoned — 0 of 37 multi-file requests produced a real
  draft-vs-signed pair (the extra files were unrelated attachments like site maps/insurance certs, not
  redlines). Check `pairing_summary.json`'s `confirmed_redlines` count before investing in the later,
  more expensive stages.
