"""
A/B check for the clustering-input reduction.

Clustering used to receive every confirmed finding in full; it now receives
distinct clause names with counts and a few truncated examples, because the
full array does not fit in a context window at population scale. That is a
prompt change to the stage that decides what the playbook's rules ARE, so it
gets validated against a known-good result rather than assumed equivalent.

Runs the one cluster call on the reduced input for the SAME findings the
previous full-payload run used, and compares topic coverage against that run's
stored output.

    python validate_cluster_reduction.py \
        --findings output/nda_mutual_confirmed.json \
        --baseline output/nda_mutual_synthesis_raw.json
"""

import argparse
import json
from pathlib import Path

import llm_azure
from azure_playbook_synthesis import CLUSTER_SCHEMA, cluster_input, cluster_prompt
from llm_azure import call_structured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True)
    parser.add_argument("--baseline", required=True,
                         help="A synthesis raw result produced with the OLD full-payload input")
    parser.add_argument("--out", default="output/cluster_reduction_check.json")
    args = parser.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))["result"]

    rows = cluster_input(findings)
    text = json.dumps(rows, indent=2)
    print(f"{len(findings):,} findings -> {len(rows):,} distinct clause names "
          f"({len(text):,} chars)")

    usage_dir = Path(__file__).parent / "output" / "usage"
    usage_dir.mkdir(parents=True, exist_ok=True)
    llm_azure.set_usage_log_path(usage_dir / "cluster_reduction_check.jsonl")

    result = call_structured(cluster_prompt(text), CLUSTER_SCHEMA, "cluster_topics",
                              call_label="cluster-reduced")
    topics = result.get("topics", [])

    base_rules = baseline.get("rules", []) + baseline.get("suggested_rules", [])
    base_titles = {r.get("title", "").lower() for r in base_rules}
    base_names = {n for r in base_rules for n in (r.get("matching_clause_names") or [])}
    new_names = {n for t in topics for n in (t.get("matching_clause_names") or [])}
    all_names = {r["clause_name"] for r in rows}

    print(f"\ntopics: baseline {len(base_rules)}  ->  reduced {len(topics)}")
    print(f"categories: {len({t['category'] for t in topics})}")
    print(f"clause-name coverage: baseline {len(base_names)}/{len(all_names)} "
          f"({len(base_names) / len(all_names) * 100:.0f}%)  ->  reduced "
          f"{len(new_names)}/{len(all_names)} ({len(new_names) / len(all_names) * 100:.0f}%)")

    # Findings reachable through each topic set — the number that actually
    # decides how much evidence reaches the drafting stage.
    counts = {r["clause_name"]: r["finding_count"] for r in rows}
    base_cov = sum(counts.get(n, 0) for n in base_names)
    new_cov = sum(counts.get(n, 0) for n in new_names)
    print(f"findings reachable: baseline {base_cov:,}/{len(findings):,} "
          f"({base_cov / len(findings) * 100:.0f}%)  ->  reduced {new_cov:,} "
          f"({new_cov / len(findings) * 100:.0f}%)")

    # A duplicated clause name means two topics would both claim the same
    # findings, double-counting evidence.
    seen, dupes = set(), set()
    for t in topics:
        for n in t.get("matching_clause_names") or []:
            (dupes if n in seen else seen).add(n)
    print(f"clause names claimed by more than one topic: {len(dupes)}"
          + (f" -> {sorted(dupes)[:5]}" if dupes else ""))

    new_titles = {t["title"].lower() for t in topics}
    print(f"\nbaseline topic titles NOT matched by name in the reduced run "
          f"({len(base_titles - new_titles)}):")
    for t in sorted(base_titles - new_titles)[:12]:
        print(f"  - {t}")
    print(f"\nnew topics not present in the baseline ({len(new_titles - base_titles)}):")
    for t in sorted(new_titles - base_titles)[:12]:
        print(f"  + {t}")

    Path(args.out).write_text(json.dumps({"topics": topics}, indent=2), encoding="utf-8")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
