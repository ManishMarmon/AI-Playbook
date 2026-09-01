"""
Regenerates requests_catalog.json (the All Requests dashboard's data) straight
from Postgres — fast, no file downloads, no LLM.

Why this is separate from run_discovery.py: that script also classifies every
FILE and (unless --skip-structure-check) downloads files to inspect them, which
takes hours across the full ~19.8k-request population. The requests catalog
needs none of that — every field is request-level metadata plus an attachment
count, all already in the database. Coupling the two meant a dashboard refresh
paid for a full file-classification sweep it never used.

Includes the two fields Jeff asked for on 2026-08-31 — has_word_redline (does
this contract have a first-cut redlined Word document?) and nda_type (mutual vs
one-way) — so the dashboard can filter, for example, US NDAs with redlines
separately from those without.

Usage:
    python -u build_requests_catalog.py
    python -u build_requests_catalog.py --out output/requests_catalog.json
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import config
import db

_FIELD_MAP = [
    ("request_id", "RequestID"),
    ("request_title", "RequestTitle"),
    ("request_status", "StatusID"),
    ("process_status", "u_RequestProcessStatus"),
    ("entry_date", "EntryDate"),
    ("contract_type", "u_RequestType"),
    ("business_sector", "u_MarmonSector"),
    ("location", "u_MarmonBusinessUnitGeography"),
    ("law_firm", "u_LawFirmName"),
    ("attorney_email", "u_HandlingAttorneyEmail"),
    ("party_a", "u_BusinessUnit"),
    ("party_b", "u_VendorCounterpartyName"),
    ("requestor", "u_Requestor"),
    ("amount", "RequestAmount"),
    ("notes", "u_Notes"),
    ("vendor_id", "VendorID"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None,
                         help="Default: output/requests_catalog.json")
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else config.OUTPUT_DIR / "requests_catalog.json"

    conn = db.get_connection()

    attachment_counts = dict(conn.execute(
        """SELECT request_id, COUNT(*) FROM files
           WHERE is_deleted IS NOT TRUE GROUP BY request_id""").fetchall())
    redline_counts = dict(conn.execute(
        """SELECT request_id, COUNT(*) FROM files
           WHERE has_tracked_changes AND is_deleted IS NOT TRUE
           GROUP BY request_id""").fetchall())
    nda_types = dict(conn.execute(
        "SELECT request_id, nda_type FROM requests WHERE nda_type IS NOT NULL").fetchall())
    scanned_requests = {r[0] for r in conn.execute(
        """SELECT DISTINCT request_id FROM files
           WHERE structure_scanned_at IS NOT NULL""").fetchall()}

    rows = conn.execute("SELECT raw FROM requests ORDER BY request_id").fetchall()
    print(f"{len(rows)} requests; {len(redline_counts)} with a tracked-changes Word redline; "
          f"{len(nda_types)} with an NDA directionality classification; "
          f"{len(scanned_requests)} structure-scanned")

    catalog = []
    for (raw,) in rows:
        rid = raw.get("RequestID")
        entry = {name: raw.get(api_field) for name, api_field in _FIELD_MAP}
        entry["attachment_count"] = attachment_counts.get(rid, 0)
        entry["has_word_redline"] = bool(redline_counts.get(rid))
        entry["word_redline_count"] = redline_counts.get(rid, 0)
        entry["nda_type"] = nda_types.get(rid)
        # Distinguishes "we looked and found no Word redline" from "we haven't
        # looked yet" — without this, an unscanned request is indistinguishable
        # from one confirmed to have no redline, which would quietly mislead
        # anyone filtering on it.
        entry["redline_scan_state"] = "scanned" if rid in scanned_requests else "not_scanned"
        catalog.append(entry)

    conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, indent=2, default=str), encoding="utf-8")

    by_state = Counter(e["redline_scan_state"] for e in catalog)
    print(f"Wrote {out_path} ({len(catalog)} rows)")
    print(f"  scan state: {dict(by_state)}")
    print(f"  has_word_redline=true: {sum(1 for e in catalog if e['has_word_redline'])}")


if __name__ == "__main__":
    main()
