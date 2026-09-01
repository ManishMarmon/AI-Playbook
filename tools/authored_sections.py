"""
Hand-authored narrative sections of the replication guide (Part 0 and
Part 7), plus the assembler that merges them with the researched subsystem
sections into the single narrative JSON consumed by build_replication_doc.py.

Usage:
    python tools/authored_sections.py --journal <workflow journal.jsonl> --out <narrative.json>
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _extractor_source() -> str:
    return (ROOT / "tools" / "extract_from_docx.py").read_text(encoding="utf-8")


def part0() -> dict:
    return {"sections": [
        {"heading": "Read This First", "level": 2, "blocks": [
            {"type": "para", "text": "This document is a complete, self-contained replication specification for the McLegal / Redline Discovery project. It is written for a Claude instance (or engineer) on a fresh Windows 11 laptop with no access to the original machine's conversation history. It has two halves: a narrative half (Parts 1-7: what the system is, exact environment, configuration contracts, runbooks, design decisions) and a mechanical half (Appendices A-C: every project source file embedded byte-exactly between marker paragraphs, with SHA-256 hashes recorded at embed time)."},
            {"type": "para", "text": "You do not retype any code. You run the extraction script once and the entire source tree materializes on disk, hash-verified. Then you follow Part 7's master checklist, which walks the parts in order."},
            {"type": "para", "text": "IMPORTANT: extract from the ORIGINAL .docx file. Do not open it in Word and re-save before extracting — a re-save can rewrite the underlying XML that extraction parses. Reading it in Word is fine; saving is not."},
        ]},
        {"heading": "Bootstrap: Re-materializing the Source Tree", "level": 2, "blocks": [
            {"type": "bullets", "items": [
                "Step 1 — Install Python (Part 2 has the exact version; any Python 3.11+ works for this step, standard library only).",
                "Step 2 — Save the extraction script below verbatim as extract_from_docx.py (it is also embedded in Appendix A as tools/extract_from_docx.py, but you need this bootstrap copy first).",
                "Step 3 — Run:  python extract_from_docx.py McLegal_Replication_Guide.docx D:\\LegalAIProjects\\AIPlaybook",
                "Step 4 — Expect every line to print OK and the final line to say all SHA-256 checks passed. Any FAIL means the .docx was modified — go back to an original copy. The target path D:\\LegalAIProjects\\AIPlaybook matches the original machine; other paths work (the code uses relative paths internally), but keeping it identical removes one source of drift.",
            ]},
            {"type": "para", "text": "Full extraction script (verbatim):"},
            {"type": "code", "text": _extractor_source()},
        ]},
        {"heading": "Marker Format Specification", "level": 2, "blocks": [
            {"type": "para", "text": "If the script is ever lost, extraction can be re-implemented from this spec. Each embedded file appears in the appendices as: one marker paragraph '\u27e6BEGIN-FILE\u27e7 path=<repo-relative-path> mode=<text|b64> eol=<LF|CRLF|NA> eofnl=<0|1|NA> sha256=<hex>', then one paragraph per line of content (tabs preserved as real tab characters; empty lines as empty paragraphs), then a closing '\u27e6END-FILE\u27e7' paragraph. For mode=text, join lines with the eol separator and append one trailing separator if eofnl=1; encode UTF-8. For mode=b64, concatenate all lines and base64-decode. Verify SHA-256 of the resulting bytes against the marker."},
        ]},
        {"heading": "What Is Deliberately NOT in This Document", "level": 2, "blocks": [
            {"type": "bullets", "items": [
                "Secrets and internal hostnames — by policy, no real credential, Key Vault URL, tenant hostname, or secret name is written here. Parts 2/3/6 contain fill-in tables of every required variable; the real values come from the original laptop's gitignored .env files (repo root and mclegal-frontend/.env) or from Azure Key Vault directly. Without those values the code runs but cannot reach CobbleStone, Key Vault, Azure OpenAI, or Postgres.",
                "Five large derived data files under mclegal-frontend/public/data/ (requests_catalog.json ~14.8 MB, clause_findings.json ~1.5 MB, redline_diffs.json ~0.8 MB, golden_rules_findings.json ~0.4 MB, redline_catalog.json ~0.2 MB). They are too large to embed as document text. Either copy them from the original machine (a plain file copy), or regenerate them with the pipeline commands in Parts 4-5. Note: requests_catalog.json regenerates deterministically from the database; the others involve LLM stages and will regenerate semantically similar but not byte-identical.",
                "The PostgreSQL data itself (~19.7k requests, ~52k files, repaired text). It is re-fetched from the live CobbleStone API by the backfill + repair runbook in Part 3 — that is the faithful path, since CobbleStone is the system of record and is itself a moving target.",
                "node_modules and Python site-packages — reinstalled from package-lock.json (embedded) and requirements.txt (embedded).",
                "Azure-side resources — an Azure Key Vault holding the MPact and Azure OpenAI secrets, and an Azure OpenAI deployment, must exist and be reachable; this document configures the client side only. The signed-in Azure identity (az login) must have Key Vault secret-read access.",
            ]},
        ]},
        {"heading": "Copy-From-Original-Laptop Manifest", "level": 2, "blocks": [
            {"type": "para", "text": "Everything a rebuild needs that is neither embedded in this document nor re-derivable, gathered in one pass. Collect these from the original laptop alongside this .docx:"},
            {"type": "table",
             "header": ["Item", "Original location", "Why it is not embedded / notes"],
             "rows": [
                ["Backend secret values", "D:\\LegalAIProjects\\AIPlaybook\\.env (gitignored)", "Secrets are excluded by policy. Copy the VALUES into the freshly created .env — the variable shape is in the embedded .env.example and Part 3's table."],
                ["Frontend secret values", "D:\\LegalAIProjects\\AIPlaybook\\mclegal-frontend\\.env (gitignored)", "Same policy. One variable: VITE_MPACT_REQUEST_URL_TEMPLATE."],
                ["requests_catalog.json (~14.8 MB)", "mclegal-frontend\\public\\data\\", "Too large to embed. Deterministic — regenerable from the DB (Part 4 map) — but copying is instant and exact."],
                ["clause_findings.json (~1.5 MB)", "mclegal-frontend\\public\\data\\", "COPY — LLM-derived; regeneration is nondeterministic and costs real Azure OpenAI tokens (~1,000+ calls)."],
                ["golden_rules_findings.json (~0.4 MB)", "mclegal-frontend\\public\\data\\", "COPY — its generator is a Claude Code Workflow script (workflows/golden_rules_review_workflow.js) that needs the Claude Code environment, not just Python."],
                ["redline_diffs.json (~0.8 MB)", "mclegal-frontend\\public\\data\\", "Deterministic from the DB; copy for exactness or regenerate per Part 4."],
                ["redline_catalog.json (~0.2 MB)", "mclegal-frontend\\public\\data\\", "Deterministic from the DB; copy for exactness or regenerate per Part 4."],
                ["aiplaybook.dump (optional, recommended)", "produce via pg_dump — command in Part 3", "The database fast path: restores ~20k requests / ~52k files with repaired text in minutes instead of ~10+ hours of live API re-fetching, and preserves the exact dataset the shipped playbooks were mined from."],
                ["docs\\audit_findings_2026-08-25.json (~0.2 MB)", "D:\\LegalAIProjects\\AIPlaybook\\docs\\ (gitignored)", "Deliberately NOT embedded: this audit record quotes the real Key Vault URL and tenant hostname it flagged, and this document must stay free of those. Copy it manually if the audit history matters on the new machine."],
             ]},
            {"type": "para", "text": "Already embedded in this document (no copying needed, despite being gitignored in the repo): CONTEXT.md, the docs/ audit and remediation Markdown records, the Freo Group AU source rulebook .docx, the project-spec .docx, both .env.example templates, all playbook JSONs, and all logo assets."},
        ]},
        {"heading": "Replication Fidelity Contract", "level": 2, "blocks": [
            {"type": "para", "text": "What 'exact same application' means here, precisely: (1) source tree byte-identical — enforced by SHA-256 at extraction; (2) toolchain versions matched to Part 2's table; (3) database schema identical (embedded SQL), database contents re-fetched from the live system rather than copied; (4) LLM-derived product artifacts (the playbook JSONs) byte-identical because they are embedded, never regenerated; (5) UI identical given the same data files. The only intentional deltas on a fresh rebuild are: newer CobbleStone data if time has passed, and the five large derived JSONs if you chose to regenerate rather than copy them."},
        ]},
    ]}


def checklist() -> dict:
    return {"sections": [
        {"heading": "Master Rebuild Order", "level": 2, "blocks": [
            {"type": "para", "text": "Run these in order. Each step names the part with full detail. Do not parallelize steps 6-10; later steps assume earlier ones completed."},
            {"type": "bullets", "items": [
                "1. Extract the source tree (Part 0 bootstrap) and confirm every SHA-256 check passed.",
                "2. Install the environment (Part 2): Python, Node, PostgreSQL 18 + pgAdmin, Azure CLI, git — exact versions per Part 2's table. Set the postgresql-x64-18 service Startup type to Automatic.",
                "3. pip install -r redline_discovery/requirements.txt  (plus pytest and python-docx per Part 2's versions table).",
                "4. Create the database per Part 3: run redline_discovery/db/setup.sql as the postgres superuser (installer password) — note psql is not on PATH; use the full path or pgAdmin's Query Tool — then EITHER restore the aiplaybook.dump fast path (recommended; Part 3, skips step 8) OR run schema.sql for the from-scratch route. Postgres port is 5433, not the default.",
                "5. Create both .env files from their .env.example templates and fill every variable using the fill-in tables (Parts 3 and 6) plus the Part 0 copy manifest. Values come from the original laptop or Key Vault — this is the one step this document cannot do for you. Belt-and-braces, pre-create gitignored output dirs: New-Item -ItemType Directory -Force redline_discovery\\output, mclegal-frontend\\public\\data",
                "6. az login with an identity that can read the Key Vault, then run Part 2's positive end-to-end Azure access check (Key Vault secret-GET + one tiny Azure OpenAI call) — not just az account show.",
                "7. Run the backend test suite: pytest (from redline_discovery/). Expect all green before touching live data.",
                "8. (Skip if the dump was restored in step 4.) Populate the database (Part 3 runbook): python -u backfill.py (hours; resumable — safe to interrupt and rerun), then python repair_text_extraction.py --limit 40 as a smoke test, then python -u repair_text_extraction.py in full (hours), then python -u sync_updates.py.",
                "9. Register the nightly scheduled task exactly as specified in Part 2.",
                "10. Frontend data: copy the five large public/data JSONs per the Part 0 copy manifest (clause_findings.json and golden_rules_findings.json must be COPIED — regeneration is nondeterministic/needs Claude Code; the other three are deterministic and may be regenerated per Part 4 instead). The playbook JSONs and the two small data JSONs were already placed by extraction. Until this step, five pages show error boxes — expected (Part 6).",
                "11. Frontend: cd mclegal-frontend, npm install (uses the embedded package-lock.json for exact versions), npx tsc --noEmit (must be clean), npm run dev.",
                "12. Run the verification checklist below, top to bottom.",
            ]},
        ]},
        {"heading": "Verification Checklist", "level": 2, "blocks": [
            {"type": "bullets", "items": [
                "Extraction reported all SHA-256 OK (Part 0).",
                "pytest passes from redline_discovery/.",
                "python validate_playbooks.py reports the embedded playbooks valid.",
                "psql: SELECT COUNT(*) FROM requests; returns roughly the Part 1 business-context scale (~19.7k+, grows over time), and SELECT COUNT(*) FROM files WHERE text_extract_repaired IS NOT NULL; is non-trivial after the repair run.",
                "npx tsc --noEmit exits clean.",
                "Dev server: every sidebar page renders with data (All Requests, Redline Discovery, Redline Diffs, Clause Findings, Reporting & Analytics, Golden Rules, Playbooks, Suggested Rules, Draft Contract).",
                "Playbooks page: Download Word on US NDA shows the suggested-rules opt-in modal; both Skip and Add-N paths produce a .docx.",
                "Theme menu (top-right kebab): Light/Dark/System all apply immediately and the choice survives a reload.",
                "mpact deep links render on All Requests / Clause Findings when VITE_MPACT_REQUEST_URL_TEMPLATE is set.",
                "One LLM smoke test (e.g. clause tagging on 2 requests per Part 5) succeeds and appends a cost entry to LLM_COST_LOG.md.",
                "Next morning: output/scheduled_refresh.log shows the nightly task ran sync + repair cleanly.",
            ]},
        ]},
        {"heading": "Operational Rules Carried Forward", "level": 2, "blocks": [
            {"type": "bullets", "items": [
                "Never commit secrets, internal hostnames, tenant URLs, or Key Vault details — real values live only in gitignored .env files. The committed .env.example files define the shape.",
                "Smoke-test every expensive LLM stage on 2-3 items before a full-batch run; cap development pipeline runs with --limit 30.",
                "The nightly scheduled task does data sync + text repair ONLY. Playbook regeneration is always a deliberate, manually-run step — shipped playbooks are never auto-overwritten.",
                "Only one data-writing job at a time: backfill, sync_updates, and repair_text_extraction all take the PID lock (data_refresh_lock.py). If one refuses to start, another is running — do not delete the lock unless you have confirmed the PID is dead.",
                "Never hold a CobbleStone bearer token in a variable across calls — always call get_bearer_token() at point of use (it caches and auto-refreshes; long runs otherwise die in a 401 storm).",
                "Append-only LLM_COST_LOG.md records every LLM run's cost — keep the convention.",
            ]},
        ]},
    ]}


# Each researched draft is identified by a heading only it contains
# (journal keys are opaque content hashes, so content is the identity).
SIGNATURE_TO_KEY = {
    "Prerequisites and Exact Versions": "env",
    "Backend Configuration Contract": "data",
    "Deterministic Pipeline Overview": "det",
    "LLM Infrastructure": "llm",
    "Frontend Architecture": "fe",
    "What This Project Is": "ov",
}


def harvest_journal(journal_path: Path) -> dict:
    """Pull each agent's structured return out of the workflow journal
    ({"type":"result","result":...} lines), identifying drafts by their
    signature headings and the critic by its verdict/gaps shape."""
    out = {}
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "result":
            continue
        r = rec.get("result")
        if not isinstance(r, dict):
            continue
        if "verdict" in r and "gaps" in r:
            out["_critique"] = r
        elif isinstance(r.get("sections"), list):
            headings = {s.get("heading", "") for s in r["sections"]}
            for sig, key in SIGNATURE_TO_KEY.items():
                if sig in headings:
                    out[key] = r
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    narrative = harvest_journal(Path(args.journal))
    missing = [k for k in ("env", "data", "det", "llm", "fe", "ov") if k not in narrative]
    narrative["part0"] = part0()
    narrative["checklist"] = checklist()
    Path(args.out).write_text(json.dumps(narrative, indent=1), encoding="utf-8")
    print(f"narrative written to {args.out}; researched keys present: "
          f"{sorted(k for k in narrative if not k.startswith('_') and k not in ('part0', 'checklist'))}")
    if missing:
        print(f"WARNING — missing researched sections: {missing}")
    if "_critique" in narrative:
        c = narrative["_critique"]
        print(f"critic verdict: {c.get('verdict')} — {len(c.get('gaps', []))} gap(s)")


if __name__ == "__main__":
    main()
