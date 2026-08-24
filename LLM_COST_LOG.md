# LLM Cost / Usage Log

Running record of every Azure OpenAI batch run against this pipeline. Token counts are exact
(from the API's own usage object); dollar cost is filled in once Marmon's actual per-token rate
for gpt-5.6-luna/terra is confirmed (see AZURE_OPENAI_PORT_PLAN.md's open questions) — never
estimated or guessed here.

| Date | Stage | Model | Requests | Calls | Input tok | Output tok | Reasoning tok | Wall time | Cost |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-25 01:03 | clause_tagging | gpt-5.6-luna | 2 | 14 | 45,172 | 30,593 | 27,999 | 3.6 min | unknown (rate not confirmed) |
| 2026-08-25 02:10 | clause_tagging | gpt-5.6-luna | 121 | 1031 | 3,990,943 | 2,254,569 | 2,022,549 | 64.6 min | unknown (rate not confirmed) |
| 2026-08-25 02:21 | playbook_synthesis | gpt-5.6-luna | 32 | 34 | 656,762 | 132,564 | 92,236 | 10.3 min | unknown (rate not confirmed) |
