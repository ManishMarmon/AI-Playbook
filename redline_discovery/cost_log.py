"""
Shared cost/usage ledger for every Azure OpenAI-backed pipeline stage (see
AZURE_OPENAI_PORT_PLAN.md). Every stage that calls llm_azure.call_structured()
should call append_cost_log_entry() once at the end of its run.

Two outputs, both committed to git (small, human-readable — the whole point
is visibility, not a private log):
  - LLM_COST_LOG.md   — one human-readable row per run, running total at top.
  - output/usage/*.jsonl  — the raw per-call log for that run (gitignored,
    like everything else in output/), for drilling into a specific call if a
    run's totals look off.

Dollar cost is left as None until a real per-token rate for gpt-5.6-luna/
terra is confirmed (these are Marmon-specific deployment names, not public
OpenAI pricing — see the port plan's open question #2). Never guess a rate;
token counts are exact, so cost math becomes a one-line fill-in once the
rate is known — every historical run's tokens are already logged.
"""

import json
from datetime import datetime
from pathlib import Path

COST_LOG_PATH = Path(__file__).parent.parent / "LLM_COST_LOG.md"

_HEADER = """# LLM Cost / Usage Log

Running record of every Azure OpenAI batch run against this pipeline. Token counts are exact
(from the API's own usage object); dollar cost is filled in once Marmon's actual per-token rate
for gpt-5.6-luna/terra is confirmed (see AZURE_OPENAI_PORT_PLAN.md's open questions) — never
estimated or guessed here.

| Date | Stage | Model | Requests | Calls | Input tok | Output tok | Reasoning tok | Wall time | Cost |
|---|---|---|---|---|---|---|---|---|---|
"""


def append_cost_log_entry(stage: str, model: str, requests_count: int, totals: dict,
                           cost_usd: float | None = None):
    """
    totals: the dict from llm_azure.get_usage_totals() — {calls, input_tokens,
    output_tokens, reasoning_tokens, cached_tokens, wall_seconds}.
    """
    if not COST_LOG_PATH.exists():
        COST_LOG_PATH.write_text(_HEADER, encoding="utf-8")

    wall_minutes = totals["wall_seconds"] / 60
    cost_str = f"${cost_usd:.2f}" if cost_usd is not None else "unknown (rate not confirmed)"
    row = (f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {stage} | {model} | {requests_count} | "
           f"{totals['calls']} | {totals['input_tokens']:,} | {totals['output_tokens']:,} | "
           f"{totals['reasoning_tokens']:,} | {wall_minutes:.1f} min | {cost_str} |\n")

    with open(COST_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(row)

    print(f"\nCost log updated: {COST_LOG_PATH}")
    print(f"  {totals['calls']} calls, {totals['input_tokens']:,} input + {totals['output_tokens']:,} "
          f"output tokens ({totals['reasoning_tokens']:,} reasoning), {wall_minutes:.1f} min wall time")
