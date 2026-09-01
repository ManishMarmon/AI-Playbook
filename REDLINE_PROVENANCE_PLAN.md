# Redline Provenance & US Mutual NDA Playbook v2 — End-to-End Plan

**Status: PLAN ONLY — no code generated yet. Each box gets checked as it ships.**

Source: Jeff's meeting guidance (2026-08-31). Core insight: a diff of *initial → final*
captures the **negotiated compromise** (both sides' edits mixed together), while a diff of
*initial → first redline* captures **Marmon's preferred position**. These are legally
different kinds of guidance. The playbook should be built from the preferred position
wherever possible, every rule must carry its comparison basis, and the analysis set is the
100–200 most recent US **mutual** NDAs that have a real redlined Word document.

Deliverable: `nda-usa-mutual` playbook, provenance-tagged, prepared for Monique's review.

**Note on Phase 0 vs Phase 1 (resolved 2026-08-31):** originally planned as a throwaway
measurement script followed by a "real" persisted scanner — merged into one, per D5 below.
There is no separate quick-and-dirty pass; the tracked-changes scanner built in Phase 1 IS
the Phase 0 measurement tool, so no file is ever downloaded and parsed twice.

## Runbook — the exact post-tagging chain

Run from `redline_discovery/`. **The order is load-bearing**, and two of the steps take
different shapes under the same `--findings` flag, so the commands are recorded verbatim
rather than left to be reconstructed.

```bash
# 0. (only if the tagger died before writing its file) rebuild it from Postgres
python -u export_clause_findings.py --population-tag nda-usa-mutual \
    --out output/nda_mutual_clause_findings.json --expected-total 100

# 1. Attribute each finding to a side. MUST precede step 2 — the array step 2
#    extracts is what synthesis rolls up, so annotating after it would leave every
#    rule reading "side unconfirmed". extract_confirmed_findings.py warns if you
#    get this wrong, but don't rely on the warning.
python -u annotate_finding_sides.py --findings output/nda_mutual_clause_findings.json

# 2. Flatten to the confirmed ARRAY that synthesis consumes
python -u extract_confirmed_findings.py --raw output/nda_mutual_clause_findings.json \
    --out output/nda_mutual_confirmed.json

# 3. Cluster into topics and draft one rule per topic (LLM; the long step)
python -u azure_playbook_synthesis.py --findings output/nda_mutual_confirmed.json \
    --sample-size 100 --min-evidence-pct 15 \
    --out output/nda_mutual_synthesis_raw.json

# 4. Write the playbook + manifest entry + methodology preface.
#    NOTE --findings here is the PAYLOAD, not the array from step 2: the
#    methodology page needs the flagged/verify-failure counts the array drops.
#    --prefix-namespace MNDA because finalize RAISES on rule-id collision and the
#    existing nda-usa playbook already owns NDA-* (NDA-PAR, NDA-SCP, NDA-HND, ...).
python -u finalize_playbook.py --raw output/nda_mutual_synthesis_raw.json \
    --id nda-usa-mutual --label "US Mutual NDA" --jurisdiction "United States" \
    --contract-types "NDA" --prefix-namespace MNDA \
    --funnel output/nda_redline_funnel.json \
    --diffs output/provenance_diffs__nda-usa-mutual.json \
    --findings output/nda_mutual_clause_findings.json \
    --min-evidence-pct 15 --tag-model gpt-5.6-luna --classifier-model gpt-5.6-terra

# 5. Structural validation of every playbook in the manifest
python -u validate_playbooks.py
```

Then annotate the existing `nda-usa` manifest label per 3.7, and generate + **read** the
Word document (`d:/tmp/pw/verify_playbook_docx.js` renders one through the real download
path and asserts the front matter).

## Progress Log
*(updated as work ships — check the plan sections above for the authoritative checkboxes)*

- 2026-08-31: Plan created; Phase 0 assumptions confirmed against live DB (US NDA
  population = 3,026 via `u_marmon_business_unit_geography = 'U.S.'`; directionality
  classification coverage = 121/3,026 = 4%). D3 and D5 resolved with Manish.
- 2026-08-31: **Phase 1 foundation complete.** Shipped `docx_redline.py`,
  `document_sequence.py`, `provenance.py`, `scan_tracked_changes.py`, `run_sequencing.py`,
  `report_redline_funnel.py`; extended `db.py` + schema (live migration applied);
  reworked `azure_nda_classifier.py` for DB persistence and the funnel loop; migrated the
  121 prior classifications into Postgres. 32 new tests, suite green at 54.
  Parser validated against 5 real contracts (one with 518 edits across two authors).
  Author attribution confirmed viable (real names + timestamps).
  Full NDA/U.S. scan running: at ~2,000/4,020 files, **68% of scanned docx files carry
  tracked changes** and 964+ requests already qualify for the funnel — the redline-having
  population will far exceed the 100–200 target rather than constrain it.
  New items surfaced during the build, appended to the plan: **1.5b** (sequencing
  persistence CLI) and the D5-driven storage of `redline_base_text` /
  `redline_proposed_text` / `tracked_change_edits`.
- 2026-08-31: **Four defects found and fixed during the Phase 3 tagging run.** All four
  were found by questioning numbers that looked plausible, not by a failing test:
  1. **`provenance_diff.py` discarded requests whose *first* redline was a textual
     no-op.** It examined only the first redline; when that document's markup produced
     no net text change it fell through to a branch requiring an `original`-role file,
     found none, and recorded `single_doc_baseline` with zero edits. Requests 19841,
     19884 and 20522 were dropped that way — each holding a Marmon-authored
     intermediate redline with 47 / 46 / 79 genuine tracked changes, i.e. **172 lost
     edits of exactly the preferred-position evidence Jeff asked for**. Now every
     redline is tried in round order; an earlier round with real edits still wins, and
     a non-first round is disclosed in `notes` because it has already absorbed some of
     the other side's changes.
  2. **A baseline note claimed "only one usable document"** on requests holding three —
     misreporting the evidence to anyone reading the provenance trail. Now states the
     actual count and the actual reason.
  3. **`llm_azure.call_structured` treated a network failure as a permanent error.**
     Transience was decided by substring-matching the message; `APIConnectionError`
     stringifies to `"Connection error."`, matching none of the patterns, so it
     re-raised out of the retry loop. A DNS blip 95 requests into a 97-request tagging
     run therefore killed the entire run. Now classified by exception **type**
     (`APIConnectionError`/`APITimeoutError`/`RateLimitError`/`InternalServerError`,
     plus retryable HTTP statuses), retries raised 4 → 6, backoff cap 30s → 60s, so a
     ~3-minute outage is survived instead of 14 seconds.
  4. **No per-request persistence, so that crash destroyed all 95 requests' LLM work.**
     Directly against the standing "nothing should go waste" rule. New sync-immune
     `clause_tagging_results` table (keyed `request_id` + `population_tag`); each
     request is committed the moment it finishes; a re-run reuses stored results.
     Reuse is gated on a `chunk_signature` hash of the diff-chunk input, so rebuilding
     the upstream diff re-tags the affected requests rather than serving findings
     derived from input that no longer exists. Failures are never cached as answers,
     and a request with no chunk file is reported rather than queued (queueing it would
     fail and persist that failure over a good stored result). A per-request exception
     no longer propagates out of the run.
  Also fixed: **`db/schema.sql` had a missing comma** (`structure_scan_note TEXT` with no
  trailing `,`) and could not execute. Live migrations had been applied with
  `ALTER TABLE`, so nobody had run the file end-to-end — but it is the from-scratch build
  path the replication guide instructs, so a clean rebuild would have failed. Now verified
  to run clean. Suite green at **116**.
- 2026-09-01: **Findings are now recoverable from Postgres, and a partial smoke test
  through the free stages found a reporting flaw before Monique could see it.**
  New `export_clause_findings.py` rebuilds the findings file from the stored per-request
  rows in exactly the shape the tagger writes. This closed the remaining half of the
  crash-safety gap: results were being persisted, but the downstream chain consumes a
  FILE the tagger only writes at the very end — so a run dying at 99/100 still had no
  usable output. `--expected-total` makes a partial export report itself as partial
  rather than letting 58 stored rows look like a complete 100.
  Used it to smoke-test the chain on real data mid-run (per the standing "smoke-test
  expensive AI workflows" rule): side annotation on 638 real findings gave
  514 Marmon preferred / 110 side-unconfirmed / 14 counterparty, and the methodology
  block built correctly from the real funnel + diffs + findings.
  **The flaw it caught:** the methodology page reported `dateRange: 27 Mar 2025 -
  28 Aug 2026`, which contradicts the funnel's "all 100 contracts from 2026" and would
  have read as a 17-month sample. Investigated rather than assumed — it is real, not a
  bug: request #20095 is a 2026 request carrying `MFT RSCS - Mutual NDA MFT redlines
  3.27.25(002).docx`, a genuine March-2025 redline. But one outlier defining the stated
  span misrepresents the sample, so `editYears` (contracts bucketed by earliest edit) is
  now reported alongside it and the page reads "…span 27 Mar 2025 - 28 Aug 2026. 98 of 99
  contracts have their edits in 2026." Both facts, no misleading summary.
  Suite green at **147** python + **23** frontend.
- 2026-09-01: **Two silent-failure modes in the post-tagging chain closed before running it.**
  Found by reading the downstream scripts' actual input handling rather than assuming the chain
  composes:
  1. **`--findings` means two different shapes.** `azure_playbook_synthesis.py` takes the flat
     confirmed ARRAY; `finalize_playbook.py` takes the tagger's whole PAYLOAD (it needs the flagged
     and verify-failure counts, which the array does not carry). Passing the array to the
     methodology builder failed several frames deep with an opaque `AttributeError`. It now raises
     a `TypeError` naming the right file.
  2. **`annotate_finding_sides.py` must run BEFORE `extract_confirmed_findings.py`**, because the
     extracted array is what synthesis clusters and rolls up. Extract first and the playbook still
     generates — every rule just silently reads "side unconfirmed" instead of naming Marmon, which
     is precisely the attribution Jeff asked for. The order is invisible from either script's
     `--help`. `extract_confirmed_findings.py` now detects the signature (findings with a
     `comparison_basis` but no `position_side`) and prints the fix. Verified live both ways:
     warns on the un-annotated payload, silent on the annotated one.
  Also confirmed `validate_playbooks.py` tolerates the new `methodology` manifest key (it checks
  named fields, not a closed schema), and that `extract_confirmed_findings.py` passes findings
  through verbatim so provenance fields survive the hop. Suite green at **148**.
- 2026-08-31: **Requests page still showed only ONE row at 1496×642 — the user's original
  complaint was never actually fixed, and this provenance work had made it worse.** The
  earlier "compact stat cards + tighter spacing" pass helped but was never verified at the
  real viewport; measuring it found the filter panel alone eating **240px of 642px**,
  because the two filters added for this feature (Word redline, NDA type) pushed a
  4-column grid from 2 rows to 3. Fixed within the user's stated constraint ("not the
  filters dropdown idea — reduce white space above and smaller card heights"):
  filter fields now flow to fit the width (`auto-fit, minmax(190px, 1fr)`) so 10 filters
  take 2 rows not 3; the "Filters" caption row was removed and Reset moved onto the title
  line, which had a screenful of unused horizontal space; and on `max-height: 780px` only,
  the outer padding, title size, table cell padding and page subtitle compact down.
  Net: filter panel 240px → 142px, table starts at y=344 instead of y=459,
  **1 row → 4 rows**; a 1000px-tall screen is unaffected and still shows 7.
  Also removed a **JS/CSS coupling bug** found on the way: `Requests.tsx` hardcoded
  `PAGE_CHROME_HEIGHT = 56 + 32 + 32`, duplicating the topbar height and page padding, so
  changing either in CSS would have silently mis-sized the scroll area. Both are now
  `--topbar-h` / `--page-pad` tokens the page reads via `calc()`.

---

## Phase 0 — Ground-truth measurement (no pipeline changes; read-only + one scan script)

The whole plan rests on one empirical question: **how many recent US mutual NDAs actually
have a tracked-changes Word document?** Jeff already flagged that missing intermediate
documents may limit the preferred-position analysis. Measure before building.

- [x] **0.1** Pull the candidate universe from Postgres: contract type NDA, location U.S.
      **DONE** — `u_request_type = 'NDA'` + `u_marmon_business_unit_geography = 'U.S.'`
      (confirmed identical to the frontend's `location` field); population **3,026**, of
      which **2,462** have at least one `.docx`.
- [x] **0.2** Scan every `.docx` in that universe for tracked changes. **DONE** — built as
      `scan_tracked_changes.py` on top of the new `docx_redline.py` parser (not the
      presence-only `structure_check` detector), persisting to Postgres.
- [x] **0.3 DONE — FUNNEL MEASURED (2026-08-31), AWAITING GATE SIGN-OFF.**
      NDA/U.S. scan is 100% complete (2,462 of 2,462 requests with a `.docx`, 4,020 files):

      | Stage | Count |
      |---|---|
      | Total US NDA requests | 3,026 |
      | ...with at least one Word `.docx` | 2,462 |
      | ...scanned | 2,462 (100%) |
      | **...with a TRACKED-CHANGES Word redline** | **2,219** (73% of docx-having) |
      | ...redline-having from 2025–2026 alone | 932 |
      | ...classified Mutual so far | 80 (all pre-2025, from the old sample) |

      Redline-having by year: 2020:6 · 2021:207 · 2022:289 · 2023:362 · 2024:423 ·
      2025:579 · 2026:353. Sequencing persisted for all 2,462: **2,219 have redline
      evidence**, request confidence high:1,986 / medium:188 / low:288; file roles
      original:2,322 · first_redline:2,216 · intermediate_redline:1,059 · final:427.

      **Conclusion: the redline population is abundant, not scarce.** Jeff's concern that
      missing intermediate documents might block preferred-position analysis does not bind
      for recent US NDAs — 932 recent candidates for a 100–200 target. The remaining
      unknown is only how many of those are *mutual*, which the classify-until-target loop
      resolves cheaply (~190 LLM calls at the historically observed ~80% mutual rate;
      the prior 121-request classification run cost ~402K tokens / 3.4 min, so this is a
      minor spend).
- [x] **0.4** Inspect `w:ins`/`w:del` markup quality. **DONE — author attribution is
      VIABLE.** Real names and timestamps present, not anonymized: e.g. "BOYD, MONIQUE",
      "Wilk, Michele", "Stackhouse, Dale", "Syvarth, Kyle", with per-edit ISO dates. D4
      therefore proceeds.
- [x] **0.5** Check existing directionality coverage. **DONE** — was 121 of 3,026 (4%),
      JSON-only; all 121 have now been migrated into Postgres so that spend is never
      repeated.

## Phase 1 — Tracked-changes parsing, DB flags, and document sequencing (foundation)

- [x] **1.1 DONE** New module `redline_discovery/docx_redline.py` — full tracked-changes parser
      (extends `structure_check.py`'s detection into extraction):
      - Parse `word/document.xml` (+ headers/footers) for `w:ins` and `w:del` elements.
      - Per edit: author (`w:author`), timestamp (`w:date`), inserted text, deleted text
        (`w:delText`), and enough surrounding context to anchor it.
      - Two derived renderings from ONE redline file: **base text** (all changes
        rejected) and **proposed text** (all changes accepted). This is the key trick:
        it yields the *initial → first-redline* diff even when the clean initial document
        was never uploaded — the redline docx contains both states.
      - Never raises; malformed docx → structured "inconclusive" result (same contract as
        `structure_check.py` / `document_extraction.py`).
- [x] **1.2 DONE (extended beyond the original plan)** Schema extension applied to
      `db/schema.sql` AND the live DB, all sync-immune:
      - `files`: `has_tracked_changes`, `tracked_change_count`, `tracked_change_authors`,
        `tracked_change_first_date`, `tracked_change_last_date`, `structure_scanned_at`,
        `document_role`, `sequence_confidence`, `sequence_reasoning`, `sequence_computed_at`
      - **Added mid-build, per D5:** `redline_base_text`, `redline_proposed_text`,
        `tracked_change_edits` — the parser's full output, not just summary counts. Without
        these, Phase 2's diff stage would have to re-download and re-parse every redline
        file; storing them means a file is fetched and parsed exactly once, ever. (The
        first scan run was deliberately stopped and restarted to capture these in one pass
        rather than adding a second download pass later.)
      - `requests`: `nda_type`, `nda_type_reasoning`, `nda_type_source_file_id`,
        `nda_type_classified_at`
- [x] **1.3 DONE** `db.py` accessors: `get_files_needing_structure_scan`,
      `save_structure_scan`, `mark_structure_scan_skipped`, `save_nda_classification`,
      `get_nda_classifications`, `get_redline_funnel_requests`.
- [x] **1.4 DONE** New CLI `scan_tracked_changes.py` — `--limit` smoke convention,
      `DataRefreshLock`, fresh `get_bearer_token()` per call, commit batching,
      recency-first work list, per-outcome counters, resumable via `structure_scanned_at`.
- [x] **1.5 DONE** New module `redline_discovery/document_sequence.py` — per-request document
      role assignment: order a request's usable documents into
      `original → first_redline → [intermediate…] → final` using, in priority order:
      (a) tracked-changes presence + internal `w:date` range, (b) file `entry_date`,
      (c) filename markers (reuse `pairing._is_final_executed` conventions),
      (d) text similarity sanity check — including the known trap where two
      similar-but-different documents (e.g. two distinct amendments, the request 264
      case) must NOT be sequenced as rounds of one negotiation. Output: labeled roles
      with a `sequence_confidence` (high/medium/low) and human-readable reasoning string.
- [x] **1.6 DONE** Unit tests — 32 new tests, full suite green at **54 passed**:
      `test_docx_redline.py` (10: insertions/deletions with authors+dates, inserted-then-
      deleted, move-text markup, formatting-only ignored, 3 malformed-input cases, real
      python-docx round-trip), `test_document_sequence.py` (10: role assignment,
      edit-date ordering beating upload order, executed-marker final, the mispairing trap,
      thin-text redline still usable), `test_provenance.py` (12).
      Also fixed a **pre-existing test-isolation defect** this work exposed: the three
      `test_sync_updates.py` tests called `main()`, which now takes the real PID
      `DataRefreshLock`, so they silently no-op'd (failing as a `KeyError`) whenever any
      real data job happened to be running. The lock is now faked in that fixture.
- [x] **1.5b DONE (added)** `run_sequencing.py` — persists computed roles/confidence/
      reasoning to the `files` columns. Free, deterministic, re-runnable.
- [x] **1.7 DONE** Nightly chain in `scheduled_data_refresh.py` is now four
      deterministic, individually-resumable stages: sync → text repair →
      `scan_tracked_changes.py` → `run_sequencing.py`. Every stage's exit code is
      reported and any failure fails the run. Still **no** automatic playbook
      regeneration — standing rule intact.

## Phase 2 — Provenance-aware findings (comparison basis on every record)

- [x] **2.1 DONE** Comparison-basis taxonomy in ONE place
      (`redline_discovery/provenance.py`) with `label()`, `describe()`, `is_preferred_
      position()`, `strongest()`, and the deterministic `rollup()` that produces the
      per-rule Basis line ("Preferred position — all 5 evidence items" / "Mixed — 14 of
      18 evidence items are a pre-compromise Marmon position"):
      - `initial_vs_first_redline` — "Marmon preferred position" (highest value, per Jeff)
      - `redline_internal` — same meaning, derived from a single tracked-changes docx
        (base-vs-proposed rendering from 1.1) when no clean initial exists
      - `initial_vs_final` — "negotiated compromise / agreed outcome" (labeled fallback)
      - `single_doc_baseline` — clean executed doc, role-model evidence (existing concept)
      - `standalone_content` — supplementary exhibits/emails (existing
        `azure_supplementary_findings.py` value, folded into the same taxonomy)
- [x] **2.2 DONE** Finding records now carry `comparison_basis`,
      `comparison_basis_label`, `source_files` (`[{file_id, file_name, role}]`),
      `edit_authors`, and `sequence_confidence` — stamped in
      `azure_clause_tagging.tag_one_request`'s `stamp()`. Additive only; every original
      field is untouched and older `run_pairing.py` chunks (which carry no provenance)
      still tag fine, with basis simply left unset rather than guessed.
      **Better than planned:** `edit_authors` is resolved PER FINDING, from the specific
      `source_edit_indices` the model cited (bounds-checked), rather than per document —
      so a finding names the attorney who actually made those edits.
- [x] **2.3 DONE** New `provenance_diff.py` + `run_provenance_diff.py`. Chooses the basis
      per request: a first redline's own base-vs-proposed renderings
      (`redline_internal`, preferred position) → else original-vs-final
      (`initial_vs_final`, labelled agreed-outcome fallback) → else
      `single_doc_baseline`. Emits chunks in exactly `run_pairing.py`'s shape so the
      tagger needed no input-format change. Per-edit authorship is matched
      bidirectionally against the stored tracked-change list (a word-level diff yields
      the minimal change "three"→"five" while the tracked change carries "three years",
      so one-directional matching missed most attributions — caught by a test).
      Unmatched edits stay `unattributed`; a wrong attribution is worse than none.
      `diffing.diff_documents` gained a `max_edits` parameter and this stage raises it to
      **250** (from the default 40, tuned for noisy text-vs-text diffs) because the live
      subset's heaviest redline carries 228 real tracked edits — truncating genuine
      negotiated wording to save prompt size is the wrong trade here.
      **Live result over the 100-request subset: 97 preferred-position, 3
      accepted-baseline, 3,648 edits, 89% attributed to a named author, zero truncated.**
- [x] **2.4 DONE — AND IT CAUGHT A REAL CORRECTNESS BUG.**
      New `author_attribution.py` + `annotate_finding_sides.py` (a post-tagging step, so
      adding this needed no re-tagging), 25 tests.
      **The bug it found:** a first-redline basis alone does NOT mean the edits are
      Marmon's. Request 20597's first redline is `...Liberty Packaging - LP REDLINE...`,
      authored by a non-Marmon editor — the COUNTERPARTY's markup of our draft. Labelling
      that "Marmon's preferred position" inverts its meaning, and Jeff's requirement is
      specifically about Marmon's position.
      **The fix:** `provenance.py` now separates the two dimensions it was conflating —
      `comparison_basis` (which versions were compared) and `position_side` (whose edits).
      Reader-facing labels: "Marmon preferred position" / "Counterparty position" /
      "Redline position (side unconfirmed)" / "Agreed outcome" / "Accepted baseline".
      `is_marmon_preferred_position()` is strict (unconfirmed side does NOT qualify) and
      `dominant_side()` refuses to call a rule ours when both sides' edits support it.
      **Live result on the 100-request subset: 78 Marmon-side, 1 counterparty, 21
      unconfirmed.** On the smoke findings, 12 findings previously all labelled
      "Preferred position" now split correctly 6 Marmon / 6 counterparty.
      Frontend follows the same rule via shared `isMarmonPreferredPosition()` /
      `basisDisplayLabel()`: green only for a position attributable to Marmon, red for a
      counterparty position, and the Word legend explains all three.
      Original plan text for this item:
      map edit authors to Marmon-side vs counterparty-side using request metadata
      (`u_HandlingAttorney`, `EnteredBy`, known-attorney list) + a manual review file for
      ambiguous names. Unknown stays `unattributed` — never guess silently.
      **Live author survey over 2,467 redline files added these requirements:**
      - **Name normalization is mandatory.** "Wilk, Michele" (1,689 files) and
        "Michele Wilk" (256 files) are the same person in two formats — without
        normalizing `Surname, Given` vs `Given Surname` (case- and punctuation-
        insensitive) any per-author rollup double-counts the single most prolific editor.
      - **Anonymized authors must map to `unattributed`, not to a person:** literal
        `"Author"` (51 files) and empty-string (3 files) come from Word privacy settings
        stripping the name.
      - **Some authors are ORGANIZATIONS, not people** (e.g. "Eversheds Sutherland", a
        law firm — and which side it acted for varies by request). Side attribution must
        come from matching against the request's own attorney/law-firm fields, never from
        assuming a firm is always Marmon's counsel.
      - Useful signal for the playbook: one Marmon attorney's edits appear in ~79% of
        redline files, which is strong prior evidence that most stored redlines really are
        Marmon-side (i.e. genuine preferred-position) edits.
- [x] **2.5 DONE** `azure_clause_tagging.py` carries provenance through Tag+Verify with the
      anti-hallucination design untouched (the verifier still checks quotes against the
      raw edits only). `tag_prompt` gained a basis-specific block: for a preferred-position
      basis it states the edits are ONE side's proposed changes and must not be described
      as agreed; for `initial_vs_final` it states they blend both parties' changes.
      **Verified live** — intent prose now reads "The redlining party sought to narrow the
      notice trigger…" rather than implying agreement.
- [x] **2.6 DONE** 24 new tests (`test_provenance.py` 12, `test_provenance_diff.py` 12)
      covering the taxonomy, rollup grammar, basis selection and its priority order,
      per-edit attribution in both directions, the abstain-rather-than-guess rule, the
      no-net-change case, the edit cap, and metadata pass-through. Full suite: **67 green**.

## Phase 3 — Scoped US mutual NDA re-mine (the actual analysis run)

- [x] **3.1 DONE — SUBSET SELECTED (2026-08-31).** `report_redline_funnel.py` implements
      the funnel and writes `output/nda_redline_funnel.json` (counts + the selected
      request ids). **N = 100 confirmed by Manish at the 0.3 gate; recent-only confirmed**
      (the 80 pre-2025 mutual NDAs from the original sample are deliberately excluded).
      Final subset: **100 mutual, redlined US NDAs, all from 2026**, date range
      2026-06-23 → 2026-08-28.
- [x] **3.2 DONE — CLASSIFICATION RUN COMPLETE (2026-08-31).** Walked the 130 most recent
      redline-having requests and found **120 Mutual (92% mutual rate** — higher than the
      old sample's 80%), then stopped, leaving 2,089 older requests untouched.
      127 LLM calls, 430K input tokens, 1.5 min wall time; logged.
      **Model substitution, deliberate and audited:** the pipeline default `gpt-5.6-luna`
      was returning HTTP 429 ("system is currently experiencing high demand") on every
      call for ~15 minutes. Auth, endpoint and code were all verified healthy
      (`gpt-5.6-terra` / `gpt-5.4-mini` / `gpt-5.2` on the same resource all worked). Before
      substituting, terra was validated against luna's existing answers on THIS task:
      **25/25 agreement (100%)** — reasonable because terra's documented weakness is
      silently merging distinct clauses, which is a clause-splitting problem irrelevant to
      a 3-way enum classification. Approved by Manish. New `requests.nda_type_model`
      column records the model per row (121 older rows backfilled as luna) and a `--model`
      flag makes the choice explicit in the command. **Clause tagging (3.4) must still use
      luna** — that is the stage where luna's accuracy advantage was actually measured.
      Previous description of this item: `azure_nda_classifier.py` reworked per D3/D5:
      persists every classification to Postgres as it lands (not JSON-only), skips
      already-classified requests unless `--reclassify`, derives party names from the
      request record so `--request-meta` is now optional, falls back to a stored redline's
      proposed text when `select_review_text` finds nothing, and adds
      `--funnel-target-mutual N` implementing the classify-newest-first-until-target loop
      so we never classify thousands of contracts to select ~150. Smoke run deferred until
      the scan finishes (Azure Key Vault auth is starved while 10 download workers are
      saturating the network — a contention artifact, not a defect).
- [ ] **3.3** Sequencing + provenance diff pass over the 150 (deterministic, free);
      review the basis mix (how many preferred-position vs fallback) before spending
      LLM tokens — **mini-gate with Manish**.
- [~] **3.4 RUNNING** Tag+Verify clause extraction over the 97 chunked requests, on
      **gpt-5.6-luna** (capacity recovered — confirmed working before launch, so the
      stage where luna's accuracy advantage was actually measured is NOT substituted).
      Smoke-tested on 2 requests first per the standing rule: 12 findings, 11 confirmed,
      1 flagged, 0 failures, and every finding carried its basis, source file, sequence
      confidence, and per-finding author. Full run in progress; ~2h expected at the
      observed rate. Output: `output/nda_mutual_clause_findings.json`.
- [ ] **3.5** Supplementary-findings pass (existing `azure_supplementary_findings.py`)
      over the same 150, same-document similarity guard as shipped.
- [ ] **3.6** Synthesis (`azure_playbook_synthesis.py`) extended so every drafted rule
      carries a **provenance rollup** — e.g. "evidence: 14 requests preferred-position,
      3 agreed-outcome, 1 baseline" — computed deterministically alongside the existing
      `evidence_count / evidence_requests / evidence_pct` math, with the dominant basis
      stored as the rule's `comparison_basis`. Per Jeff: a reader must always be able to
      tell whether a rule is a preferred starting position or an agreed outcome.
- [ ] **3.7** `finalize_playbook.py`: evidence tiering as shipped
      (`--min-evidence-pct 15`, suggested sidecar) → new playbook id **`nda-usa-mutual`**
      + `nda-usa-mutual-suggested.json`; manifest entry with
      `status: ai_draft`. Existing `nda-usa` playbook **coexists**, its manifest label
      annotated "(superseded by US Mutual NDA — kept for comparison)" — not deleted
      (decision D2 below if Manish prefers replacement).
- [ ] **3.8** `validate_playbooks.py` green over the new files; run the frontend
      docx-render path once to confirm no field breaks.

## Phase 4 — Dashboard & UI

- [x] **4.1 DONE** Catalog gains `has_word_redline`, `word_redline_count`, `nda_type`, and
      `redline_scan_state`. That last field was added beyond the plan and matters: without
      it "no redline" and "not checked yet" are indistinguishable, which would quietly
      mislead anyone filtering on it (only 3,191 of 19,809 requests are scanned so far —
      the NDA population is complete, other contract types are not).
      **New `build_requests_catalog.py`**: regenerates the catalog straight from Postgres
      in seconds with no file downloads. `run_discovery.py` also emits the new fields, but
      it classifies every FILE and downloads files to inspect them, so a dashboard refresh
      through it would have cost hours for data it never uses. Full catalog regenerated
      (19,809 rows) and deployed to the frontend.
      Also fixed there: `run_discovery.py` was re-downloading every `.docx` to check for
      tracked changes — work `scan_tracked_changes.py` had already done and stored. It now
      reuses the stored verdict and only downloads files the scan hasn't seen.
- [x] **4.2 DONE** Requests page: **"Word redline"** filter (All / Has redline / No redline
      (checked) / Not yet checked) plus an **"NDA type"** filter (Mutual / one-way), and a
      Redline column showing a chip per request ("Redline" / "2 redlines") with its NDA
      type beneath. Verified live in a browser — Jeff's exact scenario reads
      19,809 → US NDA 3,026 → has redline 2,219 → +Mutual 200, and "confirmed no redline"
      returns 243, exactly 2,462 scanned − 2,219 with redlines.
- [x] **4.3 DONE** Clause Findings page: side-aware provenance chip per finding (green for
      a Marmon preferred position, red for a counterparty position, neutral otherwise), a
      **"All positions / Marmon preferred position / Counterparty position / Side
      unconfirmed"** filter, and an "Edited by &lt;names&gt; — &lt;side summary&gt;" line showing the
      per-finding authorship from the tracked-change markup. The filter only renders when
      the loaded findings actually carry provenance, so it can't be offered as a control
      that silently matches nothing; changing it resets pagination (otherwise a narrowed
      result could leave the reader on an out-of-range empty page).
- [x] **4.4 DONE — live render check completed 2026-09-01**
      `renderPlaybookDocx.ts`: per-rule **Basis** line sits directly under
      Priority/Applies-to — green for a preferred position, slate for an agreed outcome —
      with the rollup in parentheses, plus a **"How to read Basis"** legend in the
      document's front matter explaining all three bases and stating that the counts are
      arithmetic, not an AI judgement. The legend only renders when the playbook actually
      carries provenance, so older playbooks don't gain an explanation of a field they
      lack. Playbooks page preview shows a matching Basis chip + summary line.
      `isPreferredPosition()` is exported and shared by the docx renderer and the UI, so
      the two can't drift apart on what counts as a preferred position (it mirrors
      `provenance.PREFERRED_POSITION_BASES` on the Python side).
- [x] **4.5 DONE** `npx tsc --noEmit` clean; frontend vitest 4/4; Playwright pass over the
      touched pages (light + dark) at the exact 1496×642 viewport.
      Harnesses: `d:/tmp/pw/verify_provenance_ui.js` (10 checks) and
      `verify_tall_viewport.js` (9 checks), both green.
      The provenance UI was verified against an **injected fixture** via request
      interception rather than waiting for the pipeline: the real
      `clause_findings.json` carries no provenance yet, so a screenshot of it would
      have proved nothing about the new code path. Confirmed live: green
      Marmon chip / red counterparty chip, the "Edited by …" authorship line, the
      side filter appearing only when data carries provenance, correct filtering,
      and pagination resetting instead of stranding the reader on an empty page.
      **This pass caught a real regression the earlier "compact cards" fix had not
      solved** — see the Requests-viewport entry in the progress log.

## Phase 5 — Monique's review package

- [ ] **5.1** Generate the `nda-usa-mutual` Word document (main rules; suggested-rules
      opt-in flow already exists) with the Basis column and legend.
- [x] **5.2 BUILT** (numbers land when the pipeline finishes) One-page methodology preface
      inside the doc: sample funnel with real counts and % of population, date range from
      the edits actually analysed, position-side and comparison-basis tallies, the
      Tag+Verify anti-hallucination check, evidence-tier math, and the limitations.
      New `redline_discovery/methodology.py` builds the block from the funnel JSON +
      provenance diff records + tagging output; `finalize_playbook.py` gains
      `--funnel/--diffs/--findings` (required together — partial input raises rather than
      silently shipping a document with no stated sample);
      `renderPlaybookDocx.buildMethodologySection()` renders it on its own page between
      the cover and the first rule.
      **Caveats are computed from the run's own data, never hardcoded.** This matters for
      Jeff's specific caveat: an earlier design would have printed "intermediates were
      missing, so these are agreed outcomes" on a run where all 100 contracts had real
      redline markup, understating the evidence. Now that case renders the opposite,
      truthful statement. Same for unconfirmed sides, verification gaps, tagging failures,
      the later-round disclosure, and the biggest honest limitation — that
      1,989 of 2,219 redline-having requests are not yet directionality-classified, so the
      sample is the most recent of the *confirmed* mutual NDAs, not of all that exist.
      18 python tests + 8 frontend tests, all asserting a caveat appears only when
      warranted and its opposite when not.
- [x] **5.3 BUILT** (rule ids fill in when the playbook exists) Status stays
      `ai_draft — pending attorney review`; a "What we need from you" page renders after
      the methodology preface, before the first rule — a reviewer meets the ask before
      sixty instructions, not in an appendix.
      `renderPlaybookDocx.buildHandoffSection()` derives every item from the rules in
      front of the reviewer and **names the specific rule ids** for each decision:
      priorities (always), unvetted AI language, counterparty-position rules,
      side-unconfirmed rules, agreed-outcome rules to promote/demote, and either the
      optional rules included at download time or the suggested ones held back.
      Conditional throughout — it will not send Monique hunting for counterparty rules in
      a playbook that has none, nor stay silent about ones it does have. Renders nothing
      once status is `attorney_reviewed`. 10 frontend tests.
      Caught while writing them: the asks were statically numbered, so the headings
      jumped "1." → "3." whenever the conditional language ask didn't apply. Numbering is
      now generated at emit time.

## Cross-cutting (applies to every phase)

- [ ] Smoke-test every LLM stage on 2–3 items before a batch; `--limit 30` cap while iterating.
- [ ] Every DB-writing script holds `DataRefreshLock`; never store derived flags in `raw`
      (sync clobber); fresh `get_bearer_token()` at point of use.
- [ ] `pytest` green after each phase; `LLM_COST_LOG.md` entry per LLM run.
- [ ] Nothing pushed to git (standing instruction) — commits only when Manish asks.
- [ ] At completion: update `CONTEXT.md` and rebuild `McLegal_Replication_Guide.docx`
      via `tools/build_replication_doc.py` so the replication spec stays true.

## Open decisions (need Manish / Jeff — plan proceeds with the stated defaults)

- **D1 — Subset size N**: default **150** (Jeff said 100–200); confirm at the Phase 0.3 gate
  with the real funnel numbers.
- **D2 — Old `nda-usa` playbook**: default **coexist + annotate as superseded**; alternative
  is removal once Monique approves v2.
- **D3 — "Mutual" strictness / classification order — RESOLVED 2026-08-31**: classify
  incrementally, most-recent-first, restricted to requests that already have a
  tracked-changes redline (never blanket-classify all 3,026), and **stop once the target
  mutual count (~100–150) is reached** — not before, not by exhausting the whole
  redline-having subset if target is hit early. Minimum LLM spend for a correct answer.
- **D4 — Author-side mapping**: only attempted if Phase 0.4 shows real author names; the
  playbook never depends on it (it enriches findings, it doesn't gate them).
- **D5 — Persistence — RESOLVED 2026-08-31 (Manish, explicit)**: every expensive/reusable
  primitive this plan produces MUST live in Postgres, never scratch-JSON-only, so no
  measurement or classification is ever silently repeated. Concretely: NDA directionality
  (`nda_type` + reasoning) moves from `azure_nda_classifier.py`'s JSON-only output onto new
  `requests` columns; tracked-changes scan results and document-sequence roles get new
  `files` columns — both following the exact `text_extract_repaired` pattern (new columns
  `upsert_request`/`upsert_file` never touch, so a sync can never clobber them). Phase 0's
  "measurement scan" and Phase 1's "real scanner" are therefore the SAME script/run, not
  a throwaway pass followed by a real one — see revised Phase 0/1 note below.

## Success criteria (Jeff's asks, restated as tests)

1. Every rule in `nda-usa-mutual` states its comparison basis, visible in the UI and the
   Word download. ✅ = no rule without a basis.
2. Preferred-position evidence dominates wherever a tracked-changes docx existed;
   fallbacks are labeled, never silent. ✅ = basis rollup numbers in the methodology page.
3. Dashboard can filter US NDAs by "has Word redline". ✅ = filter works on live catalog.
4. Analysis set = most recent 100–200 mutual NDAs with redlines, and the funnel that got
   there is documented with real counts. ✅ = funnel report in `output/` + methodology page.
5. Document sequencing (dates + edit history) recorded per request with confidence, per
   Jeff's progression point. ✅ = `sequence_confidence` present on findings.
6. Output prepared for Monique: single Word doc, methodology preface, ai_draft status.
