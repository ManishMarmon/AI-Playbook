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
| 2026-08-25 02:45 | clause_tagging | gpt-5.6-luna | 50 | 280 | 2,865,516 | 959,257 | 879,184 | 24.6 min | unknown (rate not confirmed) |
| 2026-08-25 02:51 | playbook_synthesis | gpt-5.6-luna | 26 | 27 | 125,907 | 83,552 | 73,146 | 6.0 min | unknown (rate not confirmed) |
| 2026-08-25 22:57 | nda_classification | gpt-5.6-luna | 3 | 3 | 9,977 | 259 | 61 | 0.4 min | unknown (rate not confirmed) |
| 2026-08-25 23:01 | nda_classification | gpt-5.6-luna | 121 | 121 | 401,995 | 16,515 | 7,700 | 3.4 min | unknown (rate not confirmed) |
| 2026-08-25 23:04 | playbook_synthesis | gpt-5.6-luna | 28 | 29 | 500,203 | 84,857 | 71,064 | 5.4 min | unknown (rate not confirmed) |
| 2026-08-25 23:52 | playbook_synthesis | gpt-5.6-luna | 22 | 23 | 118,433 | 66,728 | 57,920 | 5.3 min | unknown (rate not confirmed) |
| 2026-08-26 12:17 | supplementary_findings | gpt-5.6-luna | 2 | 145 | 1,918,057 | 107,896 | 79,318 | 10.2 min | unknown (rate not confirmed) |
| 2026-08-26 13:02 | supplementary_findings | gpt-5.6-luna | 25 | 1023 | 3,324,755 | 696,676 | 479,561 | 19.0 min | unknown (rate not confirmed) |
| 2026-08-26 13:07 | supplementary_findings | gpt-5.6-luna | 25 | 29 | 112,787 | 27,738 | 21,190 | 3.0 min | unknown (rate not confirmed) |
| 2026-08-31 16:25 | nda_classify_model_validation_terra_vs_luna_100pct_agreement | gpt-5.6-terra | 25 | 25 | 75,449 | 1,876 | 77 | 1.1 min | unknown (rate not confirmed) |
| 2026-08-31 18:54 | nda_classification | gpt-5.6-terra | 3 | 3 | 8,469 | 236 | 0 | 0.2 min | unknown (rate not confirmed) |
| 2026-08-31 18:56 | nda_classification | gpt-5.6-terra | 127 | 127 | 429,803 | 13,839 | 4,683 | 1.5 min | unknown (rate not confirmed) |
| 2026-08-31 19:10 | clause_tagging | gpt-5.6-luna | 2 | 14 | 74,044 | 25,652 | 21,666 | 2.8 min | unknown (rate not confirmed) |
| 2026-09-01 00:34 | clause_tagging | gpt-5.6-luna | 100 | 1358 | 10,373,294 | 2,119,841 | 1,815,834 | 56.2 min | unknown (rate not confirmed) |
| 2026-09-01 00:40 | playbook_synthesis | gpt-5.6-luna | 31 | 32 | 994,408 | 84,731 | 68,967 | 5.7 min | unknown (rate not confirmed) |
| 2026-09-01 01:23 | nda_classification | gpt-5.6-terra | 1989 | 1989 | 6,294,681 | 169,544 | 23,912 | 13.5 min | unknown (rate not confirmed) |
| 2026-09-01 09:11 | clause_tagging | gpt-5.6-luna | 1 | 15 | 1,138,750 | 75,778 | 72,504 | 7.6 min | unknown (rate not confirmed) |
| 2026-09-01 15:02 | clause_tagging | gpt-5.6-luna | 1023 | 12846 | 77,504,790 | 18,909,784 | 16,175,364 | 165.6 min | unknown (rate not confirmed) |
| 2026-09-01 16:22 | playbook_synthesis | gpt-5.6-luna | 40 | 43 | 804,672 | 133,101 | 109,996 | 7.6 min | unknown (rate not confirmed) |
| 2026-09-01 16:47 | playbook_synthesis | gpt-5.6-luna | 38 | 51 | 5,251,246 | 273,991 | 145,461 | 21.7 min | unknown (rate not confirmed) |
| 2026-09-01 17:01 | playbook_synthesis | gpt-5.6-luna | 37 | 50 | 5,213,474 | 242,455 | 157,790 | 9.1 min | unknown (rate not confirmed) |
