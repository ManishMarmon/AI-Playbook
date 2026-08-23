"""
Extracts the `confirmed` findings array from a clause_tagging_workflow.js raw
task result, for feeding into synthesize_playbook_workflow.js. A separate,
tiny step (rather than folding it into finalize_playbook.py) because tagging
and synthesis are two independent Workflow tool invocations run at different
times — this is the file that bridges them.

Usage:
    python extract_confirmed_findings.py --raw output/real_estate_tagging_raw.json \
        --out output/real_estate_clause_findings.json
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True,
                         help="Path to the saved raw task output from a clause_tagging_workflow.js run "
                              "(the full {summary, result, ...} object the Workflow tool returns)")
    parser.add_argument("--out", required=True,
                         help="Path to write the confirmed findings array to")
    args = parser.parse_args()

    data = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    result = data["result"]
    confirmed = result["confirmed"]

    Path(args.out).write_text(json.dumps(confirmed, indent=2), encoding="utf-8")

    print(f"Requests processed: {result['requestsProcessed']}/{result['requestsTotal']}"
          f" ({result['requestsFailed']} failed)")
    print(f"Confirmed findings: {len(confirmed)}")
    print(f"Flagged (verify rejected): {len(result['flagged'])}")
    print(f"Low/noise (discarded, not verified): {result['lowOrNoiseCount']}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
