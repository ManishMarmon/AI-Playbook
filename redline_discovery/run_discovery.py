"""
Redline Discovery Engine — v1 PoC.

Iterates CobbleStone requests, lists each request's files, classifies each
file with the v1 heuristic classifier, and writes a searchable catalog
(JSON + CSV) — the Phase 1-3 deliverable from the playbook, minus the
Word-XML / PDF-annotation / email / AI classification steps (Phase 3
techniques 2, 3, 4, 5), which are deliberately out of scope for v1.

Usage:
    python run_discovery.py --limit 200
"""

import argparse
import csv
import json
from collections import Counter

import config
from request_api import get_bearer_token, fetch_all_requests, fetch_request_file_list
from classifier import classify_file

# Mirrors pairing.py's MIN_TEXT_CHARS convention — no point spending an LLM
# call on a near-empty extract during the AI-classification fallback pass.
MIN_TEXT_CHARS_FOR_AI_FALLBACK = 200
_AI_CANDIDATE_TEXT_CHARS = 5000  # matches classifier.py's own _TEXT_SCAN_CHARS window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200,
                         help="Max number of requests to scan (default 200)")
    args = parser.parse_args()

    config.OUTPUT_DIR.mkdir(exist_ok=True)

    token = get_bearer_token()

    print(f"Fetching up to {args.limit} requests...")
    requests_ = fetch_all_requests(token, limit=args.limit)
    print(f"Requests scanned: {len(requests_)}")

    rows = []
    ai_candidates = []
    for i, req in enumerate(requests_, 1):
        request_id = req.get("RequestID")
        files = fetch_request_file_list(request_id, token)
        for f in files:
            result = classify_file(f)
            rows.append({
                "request_id": request_id,
                "request_title": req.get("RequestTitle"),
                "request_status": req.get("StatusID"),
                "request_entry_date": req.get("EntryDate"),
                "vendor_id": req.get("VendorID"),
                "file_id": f.get("ID"),
                "file_name": f.get("FileName"),
                "file_type": (f.get("FileType") or "").lower(),
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
            if (result["category"] == "Unclassified/Supporting"
                    and len(text_extract) >= MIN_TEXT_CHARS_FOR_AI_FALLBACK):
                ai_candidates.append({
                    "request_id": request_id,
                    "file_id": f.get("ID"),
                    "file_name": f.get("FileName"),
                    "file_type": (f.get("FileType") or "").lower(),
                    "heuristic_score": result["score"],
                    "text_extract": text_extract[:_AI_CANDIDATE_TEXT_CHARS],
                })
        if i % 25 == 0 or i == len(requests_):
            print(f"  ...{i}/{len(requests_)} requests processed, {len(rows)} files so far")

    json_path = config.OUTPUT_DIR / "redline_catalog.json"
    json_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

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
    print(f"AI-classification candidates (Unclassified + usable text): {len(ai_candidates)}")
    print("=" * 50)
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {ai_candidates_path}")


if __name__ == "__main__":
    main()
