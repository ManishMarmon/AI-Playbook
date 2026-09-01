"""
Guards the two mechanisms that stop expensive LLM tagging work from being lost
or silently reused when it shouldn't be.

Both exist because of a live incident (2026-08-31): a DNS blip 95 requests into
a 97-request run raised straight out of the retry loop, and because results
were only written at the very end, the whole run's LLM work was destroyed.
"""

import openai

import llm_azure
from azure_clause_tagging import plan_run


# ── Which failures are worth retrying ────────────────────────────────────────

def test_connection_error_is_transient():
    # The regression that cost a 95-request run: str(APIConnectionError) is
    # just "Connection error.", so the old substring check classified a network
    # blip as a permanent content error and re-raised immediately.
    assert llm_azure._is_transient(openai.APIConnectionError(request=None))


def test_timeout_is_transient():
    assert llm_azure._is_transient(openai.APITimeoutError(request=None))


def test_retryable_http_statuses_are_transient():
    for code in (429, 500, 502, 503, 504):
        exc = openai.APIStatusError("boom", response=_FakeResponse(code), body=None)
        assert llm_azure._is_transient(exc), f"{code} should be retried"


def test_client_error_is_not_transient():
    # A malformed request or a content/schema problem must fail fast: retrying
    # spends quota on the same wrong answer.
    exc = openai.APIStatusError("bad request", response=_FakeResponse(400), body=None)
    assert not llm_azure._is_transient(exc)


def test_arbitrary_programming_error_is_not_transient():
    assert not llm_azure._is_transient(KeyError("request_id"))


class _FakeResponse:
    """Minimal stand-in for an httpx response — APIStatusError reads
    status_code and headers off it."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.request = None


# ── Resume planning ──────────────────────────────────────────────────────────

def _ok(rid, sig):
    return {"request_id": rid, "tagging_failed": False, "chunk_signature": sig}


def test_stored_result_with_matching_signature_is_reused():
    plan = plan_run([1, 2], {1: _ok(1, "aaa")}, {1: "aaa", 2: "bbb"})
    assert plan["reused"] == [1]
    assert plan["to_process"] == [2]


def test_nothing_stored_means_everything_is_processed():
    plan = plan_run([1, 2], {}, {1: "aaa", 2: "bbb"})
    assert plan["reused"] == []
    assert plan["to_process"] == [1, 2]


def test_changed_diff_input_forces_retag():
    # The provenance-basis fix rebuilt the diffs; a stored finding derived from
    # the old chunk describes input that no longer exists and must not be
    # served as if it were current.
    plan = plan_run([1], {1: _ok(1, "old-hash")}, {1: "new-hash"})
    assert plan["stale"] == [1]
    assert plan["to_process"] == [1]
    assert plan["reused"] == []


def test_previous_failure_is_retried_not_cached_as_an_answer():
    stored = {1: {"request_id": 1, "tagging_failed": True, "chunk_signature": "aaa"}}
    plan = plan_run([1], stored, {1: "aaa"})
    assert plan["retry_failed"] == [1]
    assert plan["to_process"] == [1]
    assert plan["reused"] == []


def test_retag_flag_ignores_everything_stored():
    plan = plan_run([1, 2], {1: _ok(1, "aaa"), 2: _ok(2, "bbb")},
                    {1: "aaa", 2: "bbb"}, retag=True)
    assert plan["reused"] == []
    assert plan["to_process"] == [1, 2]


def test_processing_order_follows_the_requested_scope():
    plan = plan_run([5, 3, 9], {3: _ok(3, "x")}, {5: "a", 3: "x", 9: "c"})
    assert plan["to_process"] == [5, 9]


def test_request_with_no_chunk_file_is_never_queued():
    # A missing chunk means there is nothing to diff. Queueing it would make
    # the tagger fail, and that failure would then be persisted OVER a good
    # stored result — losing work rather than saving it.
    plan = plan_run([1], {1: _ok(1, "aaa")}, {1: None})
    assert plan["to_process"] == []
    assert plan["missing_chunk"] == [1]
    assert plan["reused"] == [1], "the stored result is the only record; keep it"


def test_missing_chunk_and_nothing_stored_is_reported_not_silently_dropped():
    plan = plan_run([1], {}, {1: None})
    assert plan["to_process"] == []
    assert plan["missing_chunk"] == [1]
    assert plan["reused"] == []


def test_stale_and_failed_requests_are_both_queued():
    stored = {
        1: _ok(1, "old"),                                                  # stale
        2: {"request_id": 2, "tagging_failed": True, "chunk_signature": "b"},  # failed
        3: _ok(3, "c"),                                                    # reusable
    }
    plan = plan_run([1, 2, 3], stored, {1: "new", 2: "b", 3: "c"})
    assert plan["to_process"] == [1, 2]
    assert plan["reused"] == [3]
    assert plan["stale"] == [1]
    assert plan["retry_failed"] == [2]
