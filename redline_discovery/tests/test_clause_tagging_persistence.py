"""
A single unstorable row must not cost the rest of the run.

Measured on the live 1,812-request run: request 6779's tagged text carried a
NUL byte, Postgres refused the statement, and because nothing rolled back the
connection stayed in an aborted-transaction state. The next 110 requests were
tagged, warned about, and never saved — a one-row problem became the loss of
every later request's work.

Two things are covered here: the NUL never reaches the driver, and a failure
that does happen leaves the connection usable.
"""

import pytest

from db import scrub_nulls


class FakeConn:
    """Mimics the part of psycopg's contract that caused the outage: once a
    statement fails, every later one fails too until the transaction ends."""

    def __init__(self, fail_on=lambda params: False):
        self.aborted = False
        self.fail_on = fail_on
        self.committed = []
        self.rollbacks = 0

    def execute(self, _sql, params=None):
        if self.aborted:
            raise RuntimeError(
                "current transaction is aborted, commands ignored until end of "
                "transaction block")
        if self.fail_on(params):
            self.aborted = True
            raise RuntimeError("unsupported Unicode escape sequence")

    def commit(self):
        self.committed.append(True)

    def rollback(self):
        self.aborted = False
        self.rollbacks += 1


# ── scrub_nulls ───────────────────────────────────────────────────────────────

def test_strips_nul_from_a_plain_string():
    assert scrub_nulls("before\x00after") == "beforeafter"


def test_keeps_every_other_character():
    # Only U+0000 is unstorable. Em-dashes, curly quotes and newlines are real
    # contract text and must survive untouched.
    text = "Confidential Information — “marked”\n\ttabbed"
    assert scrub_nulls(text) == text


def test_walks_nested_lists_and_dicts():
    payload = [{"clause": "Assign\x00ment", "notes": ["a\x00b", "c"]}]
    assert scrub_nulls(payload) == [{"clause": "Assignment", "notes": ["ab", "c"]}]


def test_leaves_non_strings_alone():
    payload = {"n": 5, "ok": True, "none": None, "f": 1.5}
    assert scrub_nulls(payload) == payload


def test_scrubs_dict_keys_too():
    assert scrub_nulls({"k\x00ey": "v"}) == {"key": "v"}


def test_handles_a_real_finding_shape():
    finding = {
        "request_id": 6779,
        "clause_name": "Return and Destruction\x00",
        "verification": {"accurate": True, "reason": "matches\x00 source"},
        "evidence": [{"before": "a\x00", "after": "b"}],
    }
    out = scrub_nulls(finding)
    assert "\x00" not in repr(out)
    assert out["request_id"] == 6779
    assert out["verification"]["accurate"] is True


def test_empty_structures_survive():
    assert scrub_nulls([]) == []
    assert scrub_nulls({}) == {}
    assert scrub_nulls("") == ""


# ── the aborted-transaction contract ─────────────────────────────────────────

def _persist(conn, request_id, failures):
    """The shape of azure_clause_tagging.persist(): warn, record, roll back."""
    try:
        conn.execute("INSERT ...", (request_id,))
        conn.commit()
    except Exception:
        failures.append(request_id)
        try:
            conn.rollback()
        except Exception:
            pass


def test_one_bad_row_does_not_block_the_next_ones():
    # This is the regression. Without the rollback, requests 2 and 3 fail too.
    conn = FakeConn(fail_on=lambda p: p == (2,))
    failures = []
    for rid in (1, 2, 3, 4):
        _persist(conn, rid, failures)
    assert failures == [2], "only the unstorable row should fail"
    assert len(conn.committed) == 3, "the other three must still commit"
    assert conn.rollbacks == 1


def test_without_rollback_the_whole_run_is_lost():
    # Documents the old behaviour, so the fix can't be quietly reverted.
    conn = FakeConn(fail_on=lambda p: p == (2,))
    failures = []
    for rid in (1, 2, 3, 4):
        try:
            conn.execute("INSERT ...", (rid,))
            conn.commit()
        except Exception:
            failures.append(rid)  # no rollback
    assert failures == [2, 3, 4]
    assert len(conn.committed) == 1


def test_failures_are_reported_not_swallowed():
    conn = FakeConn(fail_on=lambda p: p in [(2,), (5,)])
    failures = []
    for rid in range(1, 7):
        _persist(conn, rid, failures)
    assert sorted(failures) == [2, 5], "the caller must be able to name what was lost"


def test_a_failing_rollback_does_not_crash_the_run():
    class Stubborn(FakeConn):
        def rollback(self):
            raise RuntimeError("connection is closed")

    conn = Stubborn(fail_on=lambda p: p == (1,))
    failures = []
    _persist(conn, 1, failures)  # must not raise
    assert failures == [1]
