# Azure OpenAI Port Plan — moving the batch LLM stages off Claude tokens

Decision captured 2026-08-24, during the end-to-end audit session. Status of that session's
in-flight work is snapshotted at the bottom so nothing is lost across sessions.

## The problem

Every heavy LLM stage in this pipeline currently runs as a Claude Code Workflow script
(`redline_discovery/workflows/*.js`). Those calls draw from the Claude account's rolling
usage limit, and every large batch run has slammed into it:

- Phase 5 clause tagging for Equipment Leasing: 989 calls planned, interrupted at 223 by the limit.
- The end-to-end audit: map + find completed, then all ~51 verify calls + synthesis hit the limit.
- The AI-classification fallback has **never** been run on its 15,574 candidates — precisely
  because of this cost.

Marmon has an Azure AI Foundry deployment with its own (large) quota. The batch stages don't
need Claude specifically — they need a capable model behind an API.

## What moves to Azure OpenAI (plain Python, no Workflow tool)

In port order — most expensive repeat-offender first:

| # | Stage | Today | Why this order |
|---|-------|-------|----------------|
| 1 | Phase 5 clause tagging | `workflows/clause_tagging_workflow.js` | Biggest cost per playbook (~2 calls per finding across hundreds of contracts); runs once per new contract type — the direct blocker on "next 10 playbooks". |
| 2 | AI-classification fallback | `workflows/ai_classification_workflow.js` | 15,574 candidates waiting; one call each; unblocks Discovery-page completeness. |
| 3 | Playbook synthesis (cluster + draft) | `workflows/synthesize_playbook_workflow.js` | ~30 calls per playbook — cheap, but porting it makes the whole playbook build Claude-free and schedulable end to end. |
| 4 | B2 Golden Rules review | `workflows/golden_rules_review_workflow.js` | ~34 calls per contract; needed at scale only when B2 review goes wide (95+ contracts). |

Each becomes a plain Python module (e.g. `redline_discovery/llm_azure.py` client + per-stage
scripts) so it can be run by hand, from a future `run_pipeline.py` orchestrator, or on a
schedule (Task Scheduler) — with no dependency on an interactive Claude session.

## What stays on Claude

- Interactive development/orchestration (this coding session itself).
- Audit-style verify agents that need file-system access and tool use (read code, grep, run
  commands). A raw chat-completions call has no tools; building that harness is not worth it
  for occasional audits.

## Why this is also a compliance win

Azure AI Foundry inside Marmon's own tenant is a stronger data boundary for confidential
contract text than any external tool. The batch stages are exactly the ones that ship real
contract text into prompts — moving them moves the sensitive traffic inside the tenant.

## Porting notes (do not skip)

- **Structured output:** the Workflow tool enforces JSON schemas on agent returns. Azure
  OpenAI has its own JSON-schema / structured-outputs mode — the schemas in the workflow JS
  files port over, but the enforcement/retry-on-mismatch logic must be reimplemented in the
  Python client.
- **Adversarial verify step:** Phase 5's tag→verify two-stage design (and its
  verification_failed_count accounting) must be preserved — it's what keeps findings trustworthy.
- **Smoke-test discipline:** run any ported stage on 2–3 contracts and manually compare
  against the Claude-produced output for the same inputs before any full batch
  ([[feedback_smoke_test_expensive_ai_workflows]] convention).
- **Credentials:** Azure OpenAI endpoint/key go in Azure Key Vault (same pattern as the
  Mpact/CobbleStone creds in `config.py`) — never in `.env` or code.
- **Rate limits:** implement retry-with-backoff against the Azure TPM quota; unlike the
  Claude session limit, quota is per-minute, so a throttled loop completes instead of failing.

## Open questions (answer before starting the port)

1. **Which model deployment?** "5.6 terra" needs confirming in AI Foundry — the deployment
   name (gpt-4.1 / gpt-4o / o3 / gpt-5-class...) matters a lot for legal-reasoning quality.
2. **Quota shape:** tokens-per-minute or monthly allocation? Drives how aggressive the batch
   loop can be.
3. Should the ported stages write results to Postgres directly (new tables) instead of the
   current output/*.json files? (Leaning yes, but decide with the orchestrator design.)

## Relationship to the end-to-end audit

The audit's remediation plan (pending — see status below) should carry this port as a
**Strategic** item: it resolves the "LLM stages depend on interactive Claude sessions and
their account limits" gap and is a prerequisite for scheduled/orchestrated playbook production.

## Session status snapshot (2026-08-24 evening)

Everything below is paused by owner instruction — nothing is running.

- **End-to-end audit workflow** (`wf_4615d5a3-349`): Map (4/4) and Find (8/8 finders) phases
  COMPLETE — all findings cached. All ~51 Verify calls + final Synthesis failed on the Claude
  account limit (resets 11:10pm IST 2026-08-24). Resume via
  `Workflow({scriptPath: <saved script>, resumeFromRunId: 'wf_4615d5a3-349'})` — completed
  agents replay free from cache.
- **Equipment Leasing playbook build** (`wf_29d9a50c-e2f`): Phase 5 tagging interrupted by the
  same limit at 223/989 agents; resumable the same way (args must be re-supplied — they are
  recorded in the task notification's diagnostics block).
- **Crane Golden Rules validation** (197/636): deliberately parked by owner — do not resume
  without asking.
