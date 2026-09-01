"""
Covers the evidence-tier retrofit, whose job is to let an attorney revisit the
evidence bar on an already-drafted playbook without re-calling any model.

The property under test is REVERSIBILITY. The script writes only the confirmed
tier back to <id>.json and demotes the rest to <id>-suggested.json, so a run at
a stricter bar physically removes rules from the main file. If the next run read
only that file, every demoted rule would be unrecoverable and the bar could only
ever ratchet upward — which would make "try 15% and see" a one-way door on a
judgement call that is explicitly the attorney's to make.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "retrofit_evidence_tiers.py"


def rule(rule_id, names, title="T"):
    return {"rule_id": rule_id, "title": title, "matching_clause_names": names}


def finding(name, request_id):
    return {"clause_name": name, "request_id": request_id}


@pytest.fixture
def bench(tmp_path, monkeypatch):
    """A throwaway playbooks dir + findings file, so nothing touches the real
    frontend data. Runs the script in-process with PLAYBOOKS_DIR patched."""
    books = tmp_path / "playbooks"
    books.mkdir()
    sys.path.insert(0, str(SCRIPT.parent))
    import retrofit_evidence_tiers as ret

    monkeypatch.setattr(ret, "PLAYBOOKS_DIR", books)

    class Bench:
        dir = books

        def seed(self, rules, findings, suggested=None):
            (books / "manifest.json").write_text(json.dumps(
                [{"id": "pb", "file": "pb.json", "label": "PB"}]), encoding="utf-8")
            (books / "pb.json").write_text(json.dumps(rules), encoding="utf-8")
            if suggested is not None:
                (books / "pb-suggested.json").write_text(json.dumps(suggested), encoding="utf-8")
            f = tmp_path / "findings.json"
            f.write_text(json.dumps(findings), encoding="utf-8")
            self.findings = f

        def run(self, *extra, sample_size=100):
            argv = ["retrofit_evidence_tiers.py", "--playbook", "pb",
                    "--findings", str(self.findings), "--sample-size", str(sample_size), *extra]
            monkeypatch.setattr(sys, "argv", argv)
            ret.main()

        def main_rules(self):
            return json.loads((books / "pb.json").read_text(encoding="utf-8"))

        def suggested_rules(self):
            p = books / "pb-suggested.json"
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

        def manifest(self):
            return json.loads((books / "manifest.json").read_text(encoding="utf-8"))[0]

    return Bench()


# 30 requests support "Wide", 5 support "Narrow".
WIDE = [finding("Wide", i) for i in range(30)]
NARROW = [finding("Narrow", 100 + i) for i in range(5)]


def test_percentage_bar_splits_the_tiers(bench):
    bench.seed([rule("R-1", ["Wide"]), rule("R-2", ["Narrow"])], WIDE + NARROW)
    bench.run("--min-evidence-pct", "15")
    assert [r["rule_id"] for r in bench.main_rules()] == ["R-1"]
    assert [r["rule_id"] for r in bench.suggested_rules()] == ["R-2"]
    assert bench.manifest()["suggestedRulesFile"] == "pb-suggested.json"


def test_evidence_stats_are_stamped_on(bench):
    bench.seed([rule("R-1", ["Wide"])], WIDE + NARROW)
    bench.run("--min-evidence-pct", "15")
    r = bench.main_rules()[0]
    assert (r["evidence_count"], r["evidence_requests"], r["evidence_pct"]) == (30, 30, 30.0)


def test_absolute_floor_rescues_a_rule_the_percentage_bar_demotes(bench):
    # The whole point of the absolute floor: at a large sample size a real
    # pattern misses the percentage bar. 30 requests is 3% of 1,000.
    bench.seed([rule("R-1", ["Wide"])], WIDE)
    bench.run("--min-evidence-pct", "15", sample_size=1000)
    assert bench.main_rules() == []

    bench.seed([rule("R-1", ["Wide"])], WIDE)
    bench.run("--min-evidence-pct", "15", "--min-evidence-requests", "25", sample_size=1000)
    assert [r["rule_id"] for r in bench.main_rules()] == ["R-1"]


def test_absolute_floor_does_not_rescue_a_genuine_one_off(bench):
    bench.seed([rule("R-1", ["Narrow"])], NARROW)
    bench.run("--min-evidence-pct", "15", "--min-evidence-requests", "25", sample_size=1000)
    assert bench.main_rules() == []
    assert [r["rule_id"] for r in bench.suggested_rules()] == ["R-1"]


def test_a_stricter_run_then_a_looser_run_restores_the_rule(bench):
    """The reversibility property. Without pooling the sidecar back in, the
    second run would see an empty main file and could never promote R-2."""
    bench.seed([rule("R-1", ["Wide"]), rule("R-2", ["Narrow"])], WIDE + NARROW)

    bench.run("--min-evidence-pct", "15")
    assert [r["rule_id"] for r in bench.main_rules()] == ["R-1"]

    bench.run("--min-evidence-pct", "4")   # 5 of 100 requests now clears the bar
    assert sorted(r["rule_id"] for r in bench.main_rules()) == ["R-1", "R-2"]
    assert bench.suggested_rules() == []
    assert "suggestedRulesFile" not in bench.manifest()


def test_pooling_never_duplicates_a_rule_present_in_both_files(bench):
    # A stale sidecar holding a rule that is also in the main file must not
    # produce two copies of it.
    bench.seed([rule("R-1", ["Wide"])], WIDE, suggested=[rule("R-1", ["Wide"])])
    bench.run("--min-evidence-pct", "15")
    assert [r["rule_id"] for r in bench.main_rules()] == ["R-1"]


def test_retiering_is_idempotent(bench):
    bench.seed([rule("R-1", ["Wide"]), rule("R-2", ["Narrow"])], WIDE + NARROW)
    bench.run("--min-evidence-pct", "15")
    first = (bench.main_rules(), bench.suggested_rules())
    bench.run("--min-evidence-pct", "15")
    assert (bench.main_rules(), bench.suggested_rules()) == first


def test_refuses_a_playbook_with_no_findings_lineage(bench):
    # Freo Group AU is exactly this case — attorney-authored, no findings trail.
    # Fabricating evidence stats for it would be worse than refusing.
    bench.seed([{"rule_id": "R-1", "title": "T"}], WIDE)
    with pytest.raises(SystemExit) as e:
        bench.run("--min-evidence-pct", "15")
    assert "matching_clause_names" in str(e.value)


def test_rule_ids_are_not_renumbered(bench):
    bench.seed([rule("MNDA-07", ["Wide"]), rule("MNDA-02", ["Narrow"])], WIDE + NARROW)
    bench.run("--min-evidence-pct", "15")
    assert bench.main_rules()[0]["rule_id"] == "MNDA-07"
    assert bench.suggested_rules()[0]["rule_id"] == "MNDA-02"
