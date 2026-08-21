"""
Redline Discovery Engine — v1 PoC.

Iterates CobbleStone requests, lists each request's files, and classifies
each with all five playbook Phase 3 techniques in escalating cost order:
the filename/text/email/Keywords heuristic (classifier.py, free) first;
then, for anything not already written off as Likely Executed/Signed, a
structural check on the actual downloaded file bytes (structure_check.py —
Word track-changes XML / PDF annotations, a cheap API call plus a
deterministic parse, but only useful as a positive signal) — this both
resolves Unclassified rows and firms up Draft/Redline rows' confidence with
real proof; and for what's still unresolved, an LLM fallback
(workflows/ai_classification_workflow.js, run separately — this script only
emits its candidate list). Writes a searchable catalog (JSON + CSV) — the
Phase 1-3 deliverable from the playbook.

Usage:
    python run_discovery.py --limit 200
    python run_discovery.py --limit 100 --snapshot output/pipeline_snapshot.json
"""

import argparse
import csv
import json
from collections import Counter

import config
import db
from request_api import get_bearer_token, download_file, load_pipeline_snapshot
from classifier import classify_file
from structure_check import check_file_structure

# Mirrors pairing.py's MIN_TEXT_CHARS convention — no point spending an LLM
# call on a near-empty extract during the AI-classification fallback pass.
MIN_TEXT_CHARS_FOR_AI_FALLBACK = 200
# Keywords is a short free-text note, not a document body — a much lower bar
# still filters out bare tags (e.g. "LEG-100") while letting through a real
# sentence. This is what makes .msg files (routinely null TextExtract) usable
# candidates at all when CobbleStone happens to have a human-written note.
MIN_KEYWORDS_CHARS_FOR_AI_FALLBACK = 20
_AI_CANDIDATE_TEXT_CHARS = 5000  # matches classifier.py's own _TEXT_SCAN_CHARS window

# Only download+structurally-check file types we actually know how to parse.
STRUCTURE_CHECKABLE_TYPES = (".docx", ".pdf")
# Guard against a pathological outlier hanging the run — generously above the
# ~6.3MB max already seen across the current sample.
MAX_DOWNLOAD_BYTES = 20_000_000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200,
                         help="Max number of requests to scan (default 200)")
    parser.add_argument("--snapshot", default=None,
                         help="Path to a pipeline snapshot (see fetch_snapshot.py) to reuse "
                              "instead of reading from Postgres — for one-off testing against a "
                              "fixed export")
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)

    # Structure-check still needs a live token regardless of where request/file
    # metadata comes from (download_file() below hits the real API for file
    # bytes — those aren't persisted to Postgres, only TextExtract is).
    token = get_bearer_token()
    conn = db.get_connection()

    if args.snapshot:
        print(f"Loading requests + files from snapshot: {args.snapshot}")
        snapshot = load_pipeline_snapshot(args.snapshot)
        requests_ = snapshot["requests"][:args.limit] if args.limit else snapshot["requests"]
        files_by_request = snapshot["files_by_request"]
    else:
        print(f"Loading up to {args.limit} requests from Postgres...")
        requests_ = db.get_requests(conn, limit=args.limit)
        files_by_request = None
    print(f"Requests scanned: {len(requests_)}")

    rows = []
    requests_catalog = []
    ai_candidates = []
    confirmed_via_track_changes = 0
    confirmed_via_pdf_annotation = 0
    for i, req in enumerate(requests_, 1):
        request_id = req.get("RequestID")
        files = (files_by_request[request_id] if files_by_request is not None
                 else db.get_files_for_request(conn, request_id))

        # These are all already present on `req` (fetched for free — see
        # request_api.fetch_all_requests's "Fields": ["RequestID"] quirk,
        # which returns the full ~140-field record) but were previously
        # discarded entirely. One row per request, not per file.
        requests_catalog.append({
            "request_id": request_id,
            "request_title": req.get("RequestTitle"),
            "request_status": req.get("StatusID"),
            "process_status": req.get("u_RequestProcessStatus"),
            "entry_date": req.get("EntryDate"),
            "contract_type": req.get("u_RequestType"),
            "business_sector": req.get("u_MarmonSector"),
            "location": req.get("u_MarmonBusinessUnitGeography"),
            "law_firm": req.get("u_LawFirmName"),
            "attorney_email": req.get("u_HandlingAttorneyEmail"),
            "party_a": req.get("u_BusinessUnit"),
            "party_b": req.get("u_VendorCounterpartyName"),
            "requestor": req.get("u_Requestor"),
            "amount": req.get("RequestAmount"),
            "notes": req.get("u_Notes"),
            "vendor_id": req.get("VendorID"),
            "attachment_count": len(files),
        })

        for f in files:
            result = classify_file(f)
            file_type = (f.get("FileType") or "").lower()
            file_size = f.get("FileSizeBytes") or 0

            # A confirmed structural finding (real track-changes markup or PDF
            # annotations) is stronger evidence than the keyword heuristic —
            # runs on anything the heuristic didn't already write off as
            # Likely Executed/Signed, both to resolve Unclassified rows and to
            # firm up Draft/Redline rows' confidence to 100 with real proof.
            # Skipped for Likely Executed/Signed: a signed final copy isn't
            # expected to carry markup, and finding a stray comment shouldn't
            # reclassify it.
            if (result["category"] != "Likely Executed/Signed"
                    and file_type in STRUCTURE_CHECKABLE_TYPES
                    and 0 < file_size <= MAX_DOWNLOAD_BYTES):
                file_bytes = download_file(f.get("ID"), token)
                structure_hit = check_file_structure(file_type, file_bytes) if file_bytes else None
                if structure_hit:
                    result = {
                        **result,
                        "category": "Redline",
                        "confidence": 100,
                        "is_likely_redline": True,
                        "signals": result["signals"] + [structure_hit["signal"]],
                        "detection_methods": sorted(set(result["detection_methods"]) | {structure_hit["detection_method"]}),
                    }
                    if structure_hit["detection_method"] == "track_changes_xml":
                        confirmed_via_track_changes += 1
                    else:
                        confirmed_via_pdf_annotation += 1

            rows.append({
                "request_id": request_id,
                "request_title": req.get("RequestTitle"),
                "request_status": req.get("StatusID"),
                "request_entry_date": req.get("EntryDate"),
                "vendor_id": req.get("VendorID"),
                "contract_type": req.get("u_RequestType"),
                "business_sector": req.get("u_MarmonSector"),
                "location": req.get("u_MarmonBusinessUnitGeography"),
                "law_firm": req.get("u_LawFirmName"),
                "attorney_email": req.get("u_HandlingAttorneyEmail"),
                "party_a": req.get("u_BusinessUnit"),
                "party_b": req.get("u_VendorCounterpartyName"),
                "requestor": req.get("u_Requestor"),
                "file_id": f.get("ID"),
                "file_name": f.get("FileName"),
                "file_type": file_type,
                "file_entry_date": f.get("EntryDate"),
                "file_size_bytes": f.get("FileSizeBytes"),
                "category": result["category"],
                "score": result["score"],
                "confidence": result["confidence"],
                "is_likely_redline": result["is_likely_redline"],
                "signals": ";".join(result["signals"]),
                "detection_methods": ";".join(result["detection_methods"]),
            })

            text_extract = f.get("TextExtract") or ""
            keywords_raw = f.get("Keywords") or ""
            usable_text = len(text_extract) >= MIN_TEXT_CHARS_FOR_AI_FALLBACK
            usable_keywords = len(keywords_raw) >= MIN_KEYWORDS_CHARS_FOR_AI_FALLBACK
            if result["category"] == "Unclassified/Supporting" and (usable_text or usable_keywords):
                ai_candidates.append({
                    "request_id": request_id,
                    "file_id": f.get("ID"),
                    "file_name": f.get("FileName"),
                    "file_type": file_type,
                    "heuristic_score": result["score"],
                    "text_extract": text_extract[:_AI_CANDIDATE_TEXT_CHARS],
                    "keywords": keywords_raw[:_AI_CANDIDATE_TEXT_CHARS],
                })
        if i % 25 == 0 or i == len(requests_):
            print(f"  ...{i}/{len(requests_)} requests processed, {len(rows)} files so far")

    conn.close()

    json_path = config.OUTPUT_DIR / "redline_catalog.json"
    json_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    requests_catalog_path = config.OUTPUT_DIR / "requests_catalog.json"
    requests_catalog_path.write_text(json.dumps(requests_catalog, indent=2, default=str), encoding="utf-8")

    csv_path = config.OUTPUT_DIR / "redline_catalog.csv"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    attachments = len(rows)
    redlines = sum(1 for r in rows if r["is_likely_redline"])
    high_conf = sum(1 for r in rows if r["is_likely_redline"] and r["confidence"] >= 50)
    word = sum(1 for r in rows if r["is_likely_redline"] and r["file_type"] in (".docx", ".doc"))
    pdf = sum(1 for r in rows if r["is_likely_redline"] and r["file_type"] == ".pdf")

    category_counts = dict(Counter(r["category"] for r in rows))

    summary = {
        "requests_scanned": len(requests_),
        "attachments_found": attachments,
        "potential_redlines": redlines,
        "high_confidence_redlines": high_conf,
        "word_redlines": word,
        "pdf_redlines": pdf,
        "category_counts": category_counts,
        "confirmed_via_track_changes": confirmed_via_track_changes,
        "confirmed_via_pdf_annotation": confirmed_via_pdf_annotation,
    }
    summary_path = config.OUTPUT_DIR / "discovery_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    ai_candidates_path = config.OUTPUT_DIR / "ai_classification_candidates.json"
    ai_candidates_path.write_text(json.dumps(ai_candidates, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 50)
    print(f"Requests Scanned:       {len(requests_)}")
    print(f"Attachments Found:      {attachments}")
    print(f"Potential Redlines:     {redlines}")
    print(f"High Confidence (>=50): {high_conf}")
    print(f"  Word (.docx/.doc):    {word}")
    print(f"  PDF:                  {pdf}")
    print(f"Confirmed via track changes (docx):  {confirmed_via_track_changes}")
    print(f"Confirmed via PDF annotations:       {confirmed_via_pdf_annotation}")
    print(f"AI-classification candidates (Unclassified + usable text): {len(ai_candidates)}")
    print("=" * 50)
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {requests_catalog_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {ai_candidates_path}")


if __name__ == "__main__":
    main()
