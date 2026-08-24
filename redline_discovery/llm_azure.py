"""
Thin Azure OpenAI (AI Foundry) client for the batch LLM pipeline stages —
see AZURE_OPENAI_PORT_PLAN.md for why these stages moved off Claude Code
Workflow scripts.

Credentials come from the same Key Vault this project already uses for
Mpact/CobbleStone creds (config.py's pattern) — no new secrets needed.
gpt-5.6-terra/luna are deployed on the same resource as gpt-5.2/gpt-5.4-mini,
so the existing "gpt-5-4-mini-dev-api-key" secret authorizes them too
(verified live 2026-08-24 — see the port plan's sanity-test section).

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
from openai import OpenAI

# Same lookup config.py uses for _KV_URL — duplicated as a plain constant
# here rather than importing a private module attribute.
_KV_URL = os.getenv("AZURE_KEY_VAULT_URL", "https://legaldataproducts-kvault.vault.azure.net/")

DEFAULT_MODEL = "gpt-5.6-luna"
# luna is markedly more verbose than terra — 16k truncated a real response
# mid-JSON in testing, 30k was sufficient. Generous on purpose.
DEFAULT_MAX_OUTPUT_TOKENS = 30000
DEFAULT_REASONING_EFFORT = "high"

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client
    cred = DefaultAzureCredential()
    kv = SecretClient(vault_url=_KV_URL, credential=cred)
    endpoint = kv.get_secret("AOAI-dev-endpoint").value
    key = kv.get_secret("gpt-5-4-mini-dev-api-key").value
    _client = OpenAI(base_url=endpoint, api_key=key)
    return _client


class StructuredCallFailed(Exception):
    """Raised when a structured call exhausts its retries. The caller decides
    how to treat this (e.g. clause tagging marks the request tagging_failed
    rather than silently treating it as zero findings — same convention as
    clause_tagging_workflow.js)."""


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
                     max_retries: int = 4,
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
            if getattr(resp, "incomplete_details", None):
                raise StructuredCallFailed(f"Response incomplete: {resp.incomplete_details}")
            return json.loads(resp.output_text)
        except (StructuredCallFailed, json.JSONDecodeError) as e:
            last_error = e
        except Exception as e:  # noqa: BLE001 - SDK raises various transient error types
            elapsed = time.time() - t0
            _record_usage(None, model, call_label, attempt, elapsed, f"error:{type(e).__name__}")
            last_error = e
            transient = any(s in str(e).lower() for s in ("rate limit", "429", "timeout", "503", "502", "500"))
            if not transient:
                raise
        if attempt < max_retries - 1:
            sleep_s = min(2 ** attempt * 2, 30)
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
