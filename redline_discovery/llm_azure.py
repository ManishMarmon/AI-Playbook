"""
Thin Azure OpenAI (AI Foundry) client for the batch LLM pipeline stages —
see AZURE_OPENAI_PORT_PLAN.md for why these stages moved off Claude Code
Workflow scripts.

Credentials come from the same Key Vault this project already uses for
Mpact/CobbleStone creds (config.py's pattern) — secret names come from the
local .env (AOAI_ENDPOINT_SECRET_NAME/AOAI_API_KEY_SECRET_NAME, see
.env.example), never hardcoded here. gpt-5.6-terra/luna are deployed on the
same resource as gpt-5.2/gpt-5.4-mini, so the existing API key secret
authorizes them too (verified live 2026-08-24 — see the port plan's
sanity-test section).

DEFAULT_MODEL is gpt-5.6-luna, not terra: a real side-by-side test showed
terra silently merges distinct clauses together (information loss) while
luna matched or exceeded Claude's own clause-splitting granularity with zero
missed findings. Accuracy over cost/speed was an explicit owner decision.
"""

import json
import os
import threading
import time

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

import config

DEFAULT_MODEL = "gpt-5.6-luna"

# Retried on: these are all "try again", never "the request was wrong".
# Matched on TYPE, not on the message text. A substring check missed
# APIConnectionError entirely — its str() is just "Connection error.", which
# contains none of the words a text match looks for — so a momentary DNS or VPN
# blip raised straight out of the retry loop and killed a 95-request tagging run
# outright (2026-08-31). APITimeoutError subclasses APIConnectionError.
_TRANSIENT_EXCEPTIONS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
# Retryable HTTP statuses for anything the SDK surfaces as a generic
# APIStatusError rather than one of the classes above.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return True
    if isinstance(exc, APIStatusError):
        return getattr(exc, "status_code", None) in _TRANSIENT_STATUS_CODES
    # Last-resort text match, kept for error types the SDK may wrap opaquely.
    return any(s in str(exc).lower() for s in
               ("rate limit", "429", "timeout", "temporarily", "503", "502", "500"))
# luna is markedly more verbose than terra — 16k truncated a real response
# mid-JSON in testing, 30k was sufficient. Generous on purpose.
#
# Raised 30k -> 45k on 2026-09-01. Measured over the 100-request US mutual NDA
# run, tag calls output a median 11,093 tokens and a maximum of 19,422 against
# the 30k cap — comfortable there, but that run capped diff chunks at 250 edits
# and the whole-population run allows 500 (provenance_diff.MAX_REDLINE_EDITS).
# A chunk with twice the edits yields proportionally more findings, so the
# largest requests would have crept up on the ceiling, and a response truncated
# mid-JSON raises StructuredCallFailed and costs that request its whole result.
# An unused cap costs nothing, so the headroom is free insurance.
DEFAULT_MAX_OUTPUT_TOKENS = 45000
DEFAULT_REASONING_EFFORT = "high"

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client
    vault_url = config.AZURE_KEY_VAULT_URL  # side effect: loads the repo-root .env if not already loaded
    endpoint_secret = os.getenv("AOAI_ENDPOINT_SECRET_NAME")
    key_secret = os.getenv("AOAI_API_KEY_SECRET_NAME")
    if not endpoint_secret or not key_secret:
        raise RuntimeError(
            "AOAI_ENDPOINT_SECRET_NAME / AOAI_API_KEY_SECRET_NAME not set — copy .env.example to "
            ".env and fill in the Key Vault secret names for the Azure OpenAI endpoint/API key."
        )
    cred = DefaultAzureCredential()
    kv = SecretClient(vault_url=vault_url, credential=cred)
    endpoint = kv.get_secret(endpoint_secret).value
    key = kv.get_secret(key_secret).value
    _client = OpenAI(base_url=endpoint, api_key=key)
    return _client


class StructuredCallFailed(Exception):
    """Raised when a structured call exhausts its retries. The caller decides
    how to treat this (e.g. clause tagging marks the request tagging_failed
    rather than silently treating it as zero findings — same convention as
    clause_tagging_workflow.js)."""


class NonRetryableCallFailed(StructuredCallFailed):
    """A failure that the same prompt will reproduce exactly — retrying it can
    only burn the same tokens again. Subclasses StructuredCallFailed so every
    existing `except StructuredCallFailed` handler still catches it."""


_usage_lock = threading.Lock()
_usage_lock_totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                       "cached_tokens": 0, "wall_seconds": 0.0}
_usage_log_path = None  # set via set_usage_log_path(); every call appends one JSON line there


def set_usage_log_path(path):
    """Every call_structured() invocation appends its usage to this file (JSONL,
    one line per call) — see cost_report.py for turning a log into a $ estimate
    once a per-token rate is known. Call once at the start of a script."""
    global _usage_log_path
    _usage_log_path = path


def get_usage_totals() -> dict:
    return dict(_usage_lock_totals)


def call_structured(prompt: str, schema: dict, schema_name: str, *,
                     model: str = DEFAULT_MODEL,
                     max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
                     reasoning_effort: str = DEFAULT_REASONING_EFFORT,
                     max_retries: int = 6,
                     call_label: str = "") -> dict:
    """
    One schema-enforced call. Retries with exponential backoff on rate-limit/
    transient errors only (429, 5xx, timeouts) — never retries on a genuine
    content/validation problem, since retrying that just wastes quota for the
    same wrong answer. Raises StructuredCallFailed if every attempt fails.

    Every attempt's usage (successful or not, since a truncated/retried call
    still consumed real tokens) is appended to the usage log if one is set via
    set_usage_log_path() — cost tracking must reflect what was actually spent,
    not just what the final successful call used.
    """
    client = get_client()
    last_error = None
    for attempt in range(max_retries):
        t0 = time.time()
        try:
            resp = client.responses.create(
                model=model,
                input=[{"role": "user", "content": prompt}],
                max_output_tokens=max_output_tokens,
                reasoning={"effort": reasoning_effort},
                text={"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
            )
            elapsed = time.time() - t0
            _record_usage(resp, model, call_label, attempt, elapsed, "ok" if not getattr(resp, "incomplete_details", None) else "incomplete")
            incomplete = getattr(resp, "incomplete_details", None)
            if incomplete:
                usage = getattr(resp, "usage", None)
                got_in = getattr(usage, "input_tokens", None) if usage else None
                got_out = getattr(usage, "output_tokens", None) if usage else None
                detail = (f"Response incomplete: {incomplete} "
                          f"(input={got_in}, output={got_out}, cap={max_output_tokens})")
                # An output-cap overflow is DETERMINISTIC: the same prompt truncates
                # at the same place every time, so retrying it is pure waste. The
                # 2026-09-01 population cluster call proved the cost — 6 identical
                # attempts at 915,933 input tokens each, 5.5M tokens spent to learn
                # nothing, and the log gave no hint why because the reported output
                # (5,927) sat far below the 45,000 cap. It sat there because the
                # service clamps the output allowance to the context left over after
                # the input; the real problem was always an oversized prompt. Fail
                # fast and say so, so the next person reads the cause off the error.
                if getattr(incomplete, "reason", None) == "max_output_tokens":
                    if got_in and got_out and got_out < max_output_tokens * 0.9:
                        detail += ("\n  The output stopped well short of the cap, which means the "
                                   "INPUT is what left no room — shrink the prompt rather than "
                                   "raising max_output_tokens.")
                    raise NonRetryableCallFailed(detail)
                raise StructuredCallFailed(detail)
            return json.loads(resp.output_text)
        except NonRetryableCallFailed:
            raise
        except (StructuredCallFailed, json.JSONDecodeError) as e:
            last_error = e
        except Exception as e:  # noqa: BLE001 - SDK raises various transient error types
            elapsed = time.time() - t0
            _record_usage(None, model, call_label, attempt, elapsed, f"error:{type(e).__name__}")
            last_error = e
            if not _is_transient(e):
                raise
        if attempt < max_retries - 1:
            # Capped at 60s rather than 30s: a network/DNS outage lasts longer
            # than a rate-limit burst, and with 6 attempts this rides out about
            # three minutes of downtime instead of fourteen seconds.
            sleep_s = min(2 ** attempt * 2, 60)
            time.sleep(sleep_s)
    raise StructuredCallFailed(f"Exhausted {max_retries} attempts: {last_error}")


def _record_usage(resp, model, call_label, attempt, elapsed, status):
    usage = getattr(resp, "usage", None)
    entry = {
        "model": model,
        "call_label": call_label,
        "attempt": attempt,
        "status": status,
        "wall_seconds": round(elapsed, 2),
        "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
        "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
        "reasoning_tokens": getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None) if usage else None,
        "cached_tokens": getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None) if usage else None,
    }
    with _usage_lock:
        _usage_lock_totals["calls"] += 1
        _usage_lock_totals["wall_seconds"] += elapsed
        if usage:
            _usage_lock_totals["input_tokens"] += entry["input_tokens"] or 0
            _usage_lock_totals["output_tokens"] += entry["output_tokens"] or 0
            _usage_lock_totals["reasoning_tokens"] += entry["reasoning_tokens"] or 0
            _usage_lock_totals["cached_tokens"] += entry["cached_tokens"] or 0
        if _usage_log_path:
            with open(_usage_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
