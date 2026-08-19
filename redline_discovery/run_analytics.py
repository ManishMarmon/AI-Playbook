"""
Phase 6 — Reporting & Analytics.

Aggregates the outputs of Phases 1-5 (discovery_summary.json,
pairing_summary.json, redline_diffs.json, clause_findings.json) into the
operational metrics and business insights the playbook calls for. Pure
aggregation over already-generated data — no CobbleStone API calls.

Usage:
    python run_analytics.py
"""

import json
from collections import Counter, defaultdict

import config

FRONTEND_DATA_DIR = config.OUTPUT_DIR.parent.parent / "mclegal-frontend" / "public" / "data"

TOP_N = 10


def _load(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    discovery_summary = _load(config.OUTPUT_DIR / "discovery_summary.json", {})
    pairing_summary = _load(config.OUTPUT_DIR / "pairing_summary.json", {})
    diffs = _load(config.OUTPUT_DIR / "redline_diffs.json", [])
    clause_findings = _load(FRONTEND_DATA_DIR / "clause_findings.json", {"confirmed": [], "requestsProcessed": 0})

    confirmed = clause_findings.get("confirmed", [])

    # --- Operational metrics -------------------------------------------------
    paired_requests = [r for r in diffs if r.get("pairing_method") != "insufficient_files"]
    revisions_per_contract = [len(r.get("edits", [])) for r in paired_requests if r.get("edits")]
    avg_revisions = round(sum(revisions_per_contract) / len(revisions_per_contract), 1) if revisions_per_contract else 0

    operational = {
        "requests_scanned": discovery_summary.get("requests_scanned", 0),
        "attachments_found": discovery_summary.get("attachments_found", 0),
        "potential_redlines": discovery_summary.get("potential_redlines", 0),
        "confirmed_redlines": pairing_summary.get("confirmed_redlines", 0),
        "extraction_failures": pairing_summary.get("extraction_failures", 0),
        "successfully_processed": clause_findings.get("requestsProcessed", 0),
    }

    # --- Business insights -----------------------------------------------------
    clause_counter = Counter(f["clause_name"] for f in confirmed if f.get("clause_name"))
    most_negotiated_clauses = [
        {"clause_name": name, "count": count}
        for name, count in clause_counter.most_common(TOP_N)
    ]

    vendor_requests = defaultdict(set)
    vendor_finding_counts = Counter()
    for f in confirmed:
        vendor = (f.get("vendor") or "").strip()
        request_id = f.get("request_id")
        if not vendor or request_id is None:
            continue
        vendor_requests[vendor].add(request_id)
        vendor_finding_counts[vendor] += 1
    top_customers = [
        {"vendor": vendor, "requests_negotiated": len(vendor_requests[vendor]), "findings": vendor_finding_counts[vendor]}
        for vendor, _ in vendor_finding_counts.most_common(TOP_N)
    ]

    high_risk_by_request = defaultdict(lambda: {"count": 0, "request_title": None, "vendor": None})
    for f in confirmed:
        if f.get("significance") != "high":
            continue
        rid = f.get("request_id")
        if rid is None:
            continue
        entry = high_risk_by_request[rid]
        entry["count"] += 1
        entry["request_title"] = f.get("request_title")
        entry["vendor"] = f.get("vendor")
    high_risk_negotiations = sorted(
        (
            {"request_id": rid, **data}
            for rid, data in high_risk_by_request.items()
        ),
        key=lambda x: x["count"],
        reverse=True,
    )[:TOP_N]

    business_insights = {
        "most_negotiated_clauses": most_negotiated_clauses,
        "top_customers_by_negotiation_activity": top_customers,
        "average_revisions_per_contract": avg_revisions,
        "high_risk_negotiations": high_risk_negotiations,
    }

    output = {"operational": operational, "business_insights": business_insights}

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FRONTEND_DATA_DIR / "analytics.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(json.dumps(output, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
