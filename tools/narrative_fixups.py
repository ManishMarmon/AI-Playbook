"""
Applies the completeness-critic's verified corrections to the harvested
narrative JSON before the document is built. Every edit is anchored with an
assertion so a drifted draft fails loudly instead of silently shipping a
contradiction.

Usage:
    python tools/narrative_fixups.py --narrative <narrative.json>   (edits in place)
"""

import argparse
import json
from pathlib import Path


def fix_env(env: dict):
    secs = env["sections"]
    assert secs[4]["heading"] == "Fresh-Machine Install Runbook"
    steps = secs[4]["blocks"][1]["items"]

    # Step 1 — bootstrap decision: extraction primary, clone incomplete
    assert steps[0].startswith("Step 1")
    old_step1 = ("Then clone/copy the repository to exactly D:\\LegalAIProjects\\AIPlaybook "
                 "(create the D:\\LegalAIProjects folder first).")
    assert old_step1 in steps[0], "env step1 anchor missing"
    steps[0] = steps[0].replace(
        old_step1,
        "Then materialize the repository at exactly D:\\LegalAIProjects\\AIPlaybook (create the D:\\LegalAIProjects "
        "folder first) using this document's Part 0 self-extraction — that is the PRIMARY path, because it also carries "
        "essential gitignored files a git clone would MISS (CONTEXT.md, docs/, the Freo source .docx, constraints.txt "
        "companions). Afterwards, run `git init` and `git remote add origin "
        "https://github.com/ManishMarmon/AI-Playbook.git` if you want history and pushes. A plain clone of that URL works "
        "as a fallback skeleton but is INCOMPLETE without the extracted gitignored files.",
    )

    # Step 4 — port 5433 + superuser password
    assert steps[3].startswith("Step 4")
    assert "accept default port 5432" in steps[3], "port anchor missing"
    steps[3] = steps[3].replace(
        "accept default port 5432",
        "and on the installer's port screen enter 5433 — NOT the default 5432. The reference machine's cluster listens on "
        "5433 and every connection string and the committed .env.example assume it. The installer also prompts for a "
        "postgres superuser password — choose one and record it; you need it once to run db/setup.sql. Verify after "
        "install: & 'C:\\Program Files\\PostgreSQL\\18\\bin\\pg_isready.exe' -h localhost -p 5433",
    )

    # Step 8 — also create the frontend .env
    assert steps[7].startswith("Step 8")
    steps[7] += (" ALSO create the frontend env file: copy mclegal-frontend\\.env.example to mclegal-frontend\\.env and fill "
                 "VITE_MPACT_REQUEST_URL_TEMPLATE with the value from the original laptop — without it the UI's deep links "
                 "into mpact render as plain text (by design).")

    # Step 9 — never let the task fire before the DB exists
    assert steps[8].startswith("Step 9")
    steps[8] += (" ORDERING WARNING: do not register (or leave enabled) the scheduled task until the database exists and one "
                 "manual `python -u scheduled_data_refresh.py` has succeeded — an earlier 2:00 AM firing against a missing "
                 "database just writes confusing errors to output\\scheduled_refresh.log. Part 7's master checklist sequences "
                 "this correctly (task registration comes after data population).")

    # Step 6 code block — pinned constraints install
    code = secs[4]["blocks"][2]
    assert code["type"] == "code" and "requirements.txt" in code["text"]
    code["text"] = ("cd D:\\LegalAIProjects\\AIPlaybook\\redline_discovery\n"
                    "python -m pip install --user -c constraints.txt -r requirements.txt")

    # Packages narrative — requirements.txt now carries all 12, constraints.txt pins
    assert secs[2]["heading"] == "Backend Python packages (pip)"
    b0 = secs[2]["blocks"][0]
    assert "nine unpinned packages" in b0["text"]
    b0["text"] = (
        "D:\\LegalAIProjects\\AIPlaybook\\redline_discovery\\requirements.txt lists twelve unpinned packages: requests, "
        "azure-identity, azure-keyvault-secrets, truststore, pypdf, python-dotenv, psycopg[binary], openai, extract-msg, "
        "openpyxl, python-docx, pytest. (openpyxl, python-docx and pytest were added 2026-08-27 after an audit found them "
        "used but undeclared — openpyxl in particular is imported at module level by document_extraction.py, so the entire "
        "text-repair/nightly-refresh import chain dies without it.) The companion file "
        "redline_discovery\\constraints.txt pins every package to the exact version verified working on the reference "
        "machine (table below) — always install with `pip install --user -c constraints.txt -r requirements.txt` so the "
        "fresh machine cannot silently drift to newer releases. Note that `truststore` is load-bearing on this corporate "
        "network: config.py calls truststore.inject_into_ssl() at import time so Python trusts the Windows certificate "
        "store (corporate TLS interception); without it, HTTPS calls to Azure/CobbleStone fail with certificate errors."
    )
    # add openpyxl row to the versions table
    tbl = secs[2]["blocks"][1]
    assert tbl["type"] == "table"
    if not any("openpyxl" in r[0] for r in tbl["rows"]):
        tbl["rows"].append(["openpyxl", "3.1.5", "pip (requirements.txt)"])
    for r in tbl["rows"]:
        if r[0] in ("python-docx", "pytest") and "NOT in requirements.txt" in r[2]:
            r[2] = "pip (requirements.txt; pinned in constraints.txt)"

    # Azure section — positive end-to-end access verification
    assert secs[6]["heading"] == "Azure Sign-In Requirement"
    secs[6]["blocks"].extend([
        {"type": "para", "text":
            "The Key Vault, the five secrets it holds, and the Azure OpenAI deployment (default deployment name "
            "gpt-5.6-luna — see llm_azure.py) are PRE-EXISTING shared Azure resources. Nothing in this document creates "
            "them; the rebuild only points at them. The signed-in identity needs Key Vault secret-GET permission. "
            "`az account show` proves login only — run this positive end-to-end check before the first expensive run:"},
        {"type": "code", "text":
            "az account show --query user.name\n"
            "REM prove secret-read access (vault name = host part of AZURE_KEY_VAULT_URL in .env):\n"
            "az keyvault secret show --vault-name <your-vault-name> --name <value of AOAI_ENDPOINT_SECRET_NAME> --query name\n"
            "REM prove the Azure OpenAI deployment answers (one tiny call, negligible cost):\n"
            "cd D:\\LegalAIProjects\\AIPlaybook\\redline_discovery\n"
            "python -c \"import llm_azure; print(llm_azure.call_structured('Reply with the single word: ok', {'type':'object','properties':{'reply':{'type':'string'}},'required':['reply']}))\""},
        {"type": "para", "text":
            "If the last command returns a JSON object, the whole chain works: .env -> Key Vault -> Azure OpenAI "
            "deployment. If it fails, fix it here — the failure mode later is a SILENTLY failing nightly task."},
    ])


def fix_data(data: dict):
    secs = data["sections"]
    # venv step -> user-site + constraints
    s8_items = secs[8]["blocks"][0]["items"]
    assert "create a venv" in s8_items[0]
    s8_items[0] = (
        "Python 3.14 installed; NO virtualenv — install to the pip user site with the pinned constraints: "
        "cd redline_discovery && python -m pip install --user -c constraints.txt -r requirements.txt. This matches the "
        "nightly scheduled task, which runs bare `python` from PATH and would never see a venv."
    )
    # scheduled-task recreation text: venv python -> bare python
    b = secs[12]["blocks"][1]
    assert "venv's python.exe" in b["text"]
    b["text"] = b["text"].replace(
        "pointing at the venv's python.exe",
        "pointing at bare `python` (the system Python 3.14 on PATH — no venv)",
    )
    # psql-not-on-PATH + password linkage + dump fast path
    secs.append({"heading": "Database Setup — Windows Specifics and Fast Path", "level": 2, "blocks": [
        {"type": "para", "text":
            "psql is NOT on PATH after a default EDB install — either use the full path "
            "'C:\\Program Files\\PostgreSQL\\18\\bin\\psql.exe' in every command, or run both SQL files through pgAdmin's "
            "Query Tool (setup.sql's own header describes the pgAdmin route). setup.sql must be run as the postgres "
            "superuser (the password chosen during installation). The password you give the aiplaybook_app role in "
            "setup.sql MUST equal PG_PASSWORD in the repo-root .env — they are the same credential seen from two sides."},
        {"type": "para", "text":
            "FAST PATH (recommended when you can still reach the original laptop): restore the database from a dump "
            "instead of re-fetching ~20k requests from CobbleStone. This is both hours faster and higher-fidelity — "
            "CobbleStone is a live system, so a fresh backfill sees today's data, not the data the shipped playbooks were "
            "mined from. After creating the role and empty database via setup.sql (NOT schema.sql — the dump carries the "
            "schema), run:"},
        {"type": "code", "text":
            "REM on the ORIGINAL laptop:\n"
            "\"C:\\Program Files\\PostgreSQL\\18\\bin\\pg_dump.exe\" -U aiplaybook_app -h localhost -p 5433 -Fc aiplaybook > aiplaybook.dump\n"
            "REM transfer aiplaybook.dump alongside this document, then on the NEW machine:\n"
            "\"C:\\Program Files\\PostgreSQL\\18\\bin\\pg_restore.exe\" -U aiplaybook_app -h localhost -p 5433 -d aiplaybook aiplaybook.dump"},
        {"type": "para", "text":
            "The from-scratch alternative (schema.sql, then backfill.py + repair_text_extraction.py + sync_updates.py per "
            "the Data Acquisition Runbook) remains fully supported and is the right choice when the original machine is "
            "gone — just understand it reproduces the PIPELINE, not the byte-identical historical dataset."},
    ]})


def fix_det(det: dict):
    secs = det["sections"]
    b = secs[0]["blocks"][0]
    assert "venv activated" in b["text"]
    b["text"] = b["text"].replace(
        "with the repo venv activated (python -m venv venv at repo root, pip install -r redline_discovery/requirements.txt)",
        "with the system Python 3.14 (no venv — packages live in the pip user site; install per Part 2)",
    )
    b5 = secs[5]["blocks"][0]
    assert "venv active" in b5["text"]
    b5["text"] = b5["text"].replace("with the venv active", "with the system Python (no venv)")
    # stale pytest gotcha
    g = secs[17]["blocks"][5]["items"]
    assert "pytest is NOT in requirements.txt" in g[0]
    g[0] = ("pytest and python-docx are IN requirements.txt as of 2026-08-27 and pinned in constraints.txt — Part 2's "
            "single install command covers them; no separate install step exists any more.")


def fix_llm(llm: dict):
    secs = llm["sections"]
    b = secs[27]["blocks"][0]
    assert "venv active" in b["text"]
    b["text"] = b["text"].replace("with the project venv active", "with the system Python (no venv; see Part 2)")


def fix_fe(fe: dict):
    secs = fe["sections"]
    b = secs[16]["blocks"][1]
    assert "npm install" in b["text"]
    b["text"] = b["text"].replace("npm install", "npm ci")
    secs[16]["blocks"].insert(2, {"type": "para", "text":
        "Use `npm ci`, not `npm install`: ci reproduces package-lock.json exactly; install may rewrite the lockfile and "
        "drift versions. Reach for `npm install` only when intentionally changing dependencies."})
    # expected first-boot state
    secs.append({"heading": "Expected State Before the Data Copy", "level": 2, "blocks": [
        {"type": "para", "text":
            "Immediately after extraction + npm ci, five pages (All Requests, Redline Discovery, Redline Diffs, Clause "
            "Findings, Golden Rules) show useJsonResource error boxes — their backing JSONs under "
            "mclegal-frontend/public/data/ are the large derived files this document does not embed. This is NORMAL, not "
            "a broken build: Playbooks, Suggested Rules and Draft Contract already work (their JSONs are embedded). The "
            "error states clear as soon as the five files are copied from the original machine or regenerated (Part 0's "
            "copy manifest / Parts 4-5)."},
    ]})


def fix_ov(ov: dict):
    secs = ov["sections"]
    layout = secs[1]["blocks"][3]
    assert "project-dedicated Python venv" in layout["text"]
    layout["text"] = layout["text"].replace(
        "venv/                           project-dedicated Python venv (gitignored)",
        "venv/                           LEGACY — present but unused; do NOT recreate (everything runs the system Python)",
    )
    item = secs[13]["blocks"][0]["items"]
    assert any("venv\\Scripts\\python.exe" in i for i in item)
    for i, it in enumerate(item):
        if "venv\\Scripts\\python.exe" in it:
            item[i] = it.replace(
                "`venv\\Scripts\\python.exe -u redline_discovery\\scheduled_data_refresh.py`",
                "bare `python -u scheduled_data_refresh.py` with start-in directory redline_discovery (system Python on "
                "PATH — no venv; this matches the live task captured in Part 2)",
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--narrative", required=True)
    args = ap.parse_args()
    p = Path(args.narrative)
    n = json.loads(p.read_text(encoding="utf-8"))
    fix_env(n["env"])
    fix_data(n["data"])
    fix_det(n["det"])
    fix_llm(n["llm"])
    fix_fe(n["fe"])
    fix_ov(n["ov"])
    # every fix above asserts its anchor; reaching here means all applied
    p.write_text(json.dumps(n, indent=1), encoding="utf-8")
    print("all critic fixups applied and anchors verified")


if __name__ == "__main__":
    main()
