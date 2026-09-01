"""
Nightly-scheduled data refresh, four deterministic stages in order:
  1. sync_updates.py          — pull new requests, refresh active requests'
                                file lists from CobbleStone
  2. repair_text_extraction.py — recover text for files CobbleStone's own
                                extraction left empty (every newly-synced file
                                has the same broken-extraction problem as the
                                rest of the population, confirmed live to be a
                                service-wide issue since ~2023, not something
                                that self-corrects for new uploads)
  3. scan_tracked_changes.py   — parse newly-synced .docx files for Word
                                tracked changes and store the redline
                                base/proposed renderings and per-edit
                                authorship (see docx_redline.py)
  4. run_sequencing.py         — recompute each request's document-sequence
                                roles from what stage 3 stored

None of the four calls an LLM, and each is individually resumable, so a night
that gets cut short simply continues the next one.

Deliberately stops here, per explicit decision: pairing/clause-tagging/
synthesis and regenerating a shipped playbook all stay separate, manually
triggered steps — this script only keeps the underlying data current, it
never touches anything under mclegal-frontend/public/playbooks/.

Runs as a Windows Scheduled Task under the same Windows user account that's
already `az login`'d (confirmed live: config.py's Key Vault access uses
DefaultAzureCredential, which picks up that cached Azure CLI session
non-interactively — no service principal or extra setup needed). This DOES
mean the task silently starts failing if that az login session is ever
revoked or expires; check output/scheduled_refresh.log if new data stops
appearing after a previously-working stretch, and re-run `az login` if so.

Usage:
    python -u scheduled_data_refresh.py
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import db

SCRIPT_DIR = Path(__file__).parent


def _run(script_name: str, *script_args: str) -> int:
    label = " ".join([script_name, *script_args])
    print(f"\n{'=' * 60}\n{datetime.now().isoformat()}  Running {label}\n{'=' * 60}", flush=True)
    result = subprocess.run(
        [sys.executable, "-u", str(SCRIPT_DIR / script_name), *script_args], cwd=SCRIPT_DIR)
    return result.returncode


def main():
    start = time.time()
    print(f"Scheduled data refresh starting at {datetime.now().isoformat()}", flush=True)

    sync_rc = _run("sync_updates.py")

    conn = db.get_connection()
    sync_status = db.get_sync_state(conn)["last_run_status"]
    conn.close()
    print(f"\nsync_updates.py exit code: {sync_rc}, last_run_status in DB: {sync_status}", flush=True)

    repair_rc = _run("repair_text_extraction.py")

    # Tracked-changes structure scan: newly-synced .docx files need the same
    # one-time parse as everything else, so "which contracts have a real Word
    # redline" stays current without anyone re-running it by hand. Deterministic
    # and free (download + local parse, no LLM), and resumable, so a partial
    # night simply continues tomorrow. Deliberately still NOT playbook
    # regeneration — that stays manual, per the standing rule.
    scan_rc = _run("scan_tracked_changes.py")

    # Sequencing consumes only what the scan just stored (no network, no LLM),
    # so roles/confidence stay in step with the newly-scanned files.
    sequence_rc = _run("run_sequencing.py")

    elapsed = time.time() - start
    print(f"\n{'=' * 60}", flush=True)
    print(f"Scheduled data refresh finished in {elapsed / 60:.1f} min", flush=True)
    print(f"  sync_updates.py:           exit={sync_rc}, last_run_status={sync_status}", flush=True)
    print(f"  repair_text_extraction.py: exit={repair_rc}", flush=True)
    print(f"  scan_tracked_changes.py:   exit={scan_rc}", flush=True)
    print(f"  run_sequencing.py:         exit={sequence_rc}", flush=True)
    print(f"{'=' * 60}", flush=True)

    if (sync_rc != 0 or sync_status == "pass2_failed" or repair_rc != 0
            or scan_rc != 0 or sequence_rc != 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
