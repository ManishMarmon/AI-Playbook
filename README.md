# AI Playbook — Redline Document Intelligence

AI system that discovers, extracts, and analyzes redline (negotiation/markup) documents from Marmon's CobbleStone/Mpact contract requests, and surfaces the results on a dashboard.

## Architecture

Six phases, following the original playbook design:

| Phase | Description | Status |
|---|---|---|
| 1 — Request Discovery | Pull contract requests from the CobbleStone API, filter by year/type/status | Done |
| 2 — File Discovery | Catalog every attachment per request (Word, PDF, MSG, EML, ...) | Done |
| 3 — Redline Identification | Classify each document as Executed / Draft / Negotiation Copy / Redline / Supporting / Email | Done |
| 4 — Redline Extraction | Pair each redline against its original and word-diff them | Done |
| 5 — AI Understanding | Merge raw diffs into clause-level findings, adversarially verify each one | Done |
| 6 — Reporting & Analytics | Aggregate metrics and business insights (most-negotiated clauses, risk rollups, ...) | Not started |

## Repository layout

```
redline_discovery/          Phases 1-5 pipeline (Python)
  config.py                 CobbleStone/Mpact API config; credentials via Azure Key Vault
  request_api.py            CobbleStone API client (auth, pagination, file download)
  run_discovery.py          Phase 1-3 entry point — discovers and classifies redlines
  classifier.py             Redline/draft/executed classification heuristics (filename/text/email/Keywords)
  structure_check.py        Phase 3 techniques 2/3 — Word track-changes XML / PDF-annotation
                              detection on the actual downloaded file bytes
  pairing.py                Phase 4 — pairs a redline file against its original
  diffing.py                Phase 4 — word-level diff between original and redline text
  run_pairing.py            Phase 4 entry point — pairs + diffs a batch of requests
  workflows/
    clause_tagging_workflow.js   Phase 5 — tag + adversarially verify clause-level findings
                                  (runs via Claude Code's Workflow tool, not standalone Node)
    ai_classification_workflow.js  Phase 3 fallback — LLM judgment on attachments the
                                  filename/text heuristic left Unclassified (same Workflow-tool
                                  pattern as clause_tagging_workflow.js)

mclegal-frontend/           Dashboard (React + Vite)
  src/pages/                Redline Discovery, Redline Diffs, Clause Findings
```

## Running the pipeline

Credentials (Mpact OAuth client ID/secret) are pulled at runtime from Azure Key Vault via `DefaultAzureCredential` — nothing is stored in this repo. Set `AZURE_KEY_VAULT_URL` if it differs from the default in `config.py`.

```bash
python -m venv venv
venv/Scripts/activate   # or source venv/bin/activate on macOS/Linux
pip install -r redline_discovery/requirements.txt

cd redline_discovery
python run_discovery.py --limit 200      # Phases 1-3: discover + classify
python run_pairing.py --limit 200        # Phase 4: pair + diff
```

Phase 5 (`workflows/clause_tagging_workflow.js`) is invoked through Claude Code's Workflow tool with `args: { chunkDir, requestIds }`, where `chunkDir` points at the per-request diff JSON files produced by `run_pairing.py`.

For attachments the filename/text/email/Keywords heuristic leaves "Unclassified/Supporting" (`.docx`/`.pdf` only, under 20MB), `run_discovery.py` downloads the actual file via `request_api.download_file()` (the `Files/ContractFilesEXt/Download` endpoint — returns a `multipart/mixed` response; CobbleStone's own metadata endpoints never returned real file bytes before this) and runs `structure_check.py` against it: real Word track-changes XML (`<w:ins>`/`<w:del>`) or PDF markup annotations are strictly stronger evidence than any keyword match, so a hit overrides the row to `category: "Redline"`, `confidence: 100`. A miss (or a file type/size this doesn't cover, e.g. `.doc`) falls through to the next step unchanged. Downloaded bytes are never written to disk or logged — only booleans/counts — since these are real confidential business documents.

Whatever's still "Unclassified/Supporting" after that becomes an AI-classification-fallback candidate, written to `output/ai_classification_candidates.json`. To run it: read that file, invoke `workflows/ai_classification_workflow.js` through Claude Code's Workflow tool with `args: { candidates: <its contents> }`, then save the workflow's return value to `output/ai_classification_results.json` yourself (this workflow, like Phase 5's, doesn't write its own output — see `clause_findings.json`'s handling for why). Smoke-test on a handful of candidates before running the full batch; each candidate costs one LLM call.

## Running the dashboard

```bash
cd mclegal-frontend
npm install
npm run dev
```

The dashboard reads its data from `public/data/*.json`. These files aren't checked into this repo (they're generated output, not source) — copy the corresponding files from `redline_discovery/output/` after running the pipeline.
