"""
Guards against two data-writing jobs (sync_updates.py, repair_text_extraction.py)
running against the same Postgres tables at once.

Live-confirmed necessity: on 2026-08-26, a manually-launched full-population
repair_text_extraction.py run was still in progress (started that afternoon,
CobbleStone's API turned out to be slow enough that 35,623 files took many
hours) when the 2am-scheduled scheduled_data_refresh.py fired anyway, ran
sync_updates.py, then started a SECOND repair_text_extraction.py — two
processes concurrently UPDATEing the files table deadlocked each other
(psycopg.errors.DeadlockDetected) and killed the first (manual) run outright.
Neither script had any notion that the other might already be running.

Usage: wrap a script's DB-writing body in `with DataRefreshLock(): ...` —
raises RuntimeError immediately (before any DB connection is opened) if
another instance already holds the lock, rather than proceeding to collide.
"""

import os
import subprocess
from pathlib import Path

LOCK_PATH = Path(__file__).parent / "output" / ".data_refresh.lock"


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True, text=True,
    )
    return str(pid) in out.stdout


class DataRefreshLock:
    def __enter__(self):
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_PATH.exists():
            held_pid_text = LOCK_PATH.read_text(encoding="utf-8").strip()
            held_pid = int(held_pid_text) if held_pid_text.isdigit() else None
            if held_pid and _pid_alive(held_pid):
                raise RuntimeError(
                    f"Another data-refresh process (PID {held_pid}) is already running — "
                    f"refusing to start a second one and risk the concurrent-write deadlock "
                    f"seen on 2026-08-26. If that process is confirmed no longer running, "
                    f"delete {LOCK_PATH} and retry."
                )
            # Stale lock left behind by a crashed run — safe to reclaim.
        LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
                LOCK_PATH.unlink()
        except OSError:
            pass
        return False
