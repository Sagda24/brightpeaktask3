# Context Management Strategy Comparison

10-transcript BrightPeak advising-call long-context test suite (see transcripts.py). Each transcript buries one critical eligibility fact (a prerequisite waiver, a cleared registration hold, a credit-overload exception, or approved transfer credit) under 28-40 turns of tool-heavy noise, then asks the agent to account for it on the final turn.

| Strategy | Critical fact recalled correctly | Avg. input tokens/run | Avg. output tokens/run | Avg. latency |
|---|---|---|---|---|
| Sliding window (last 10 turns) | 0/10 | 544 | 40 | 0.77s |
| Observation/tool-output masking (keep last 3) | 10/10 | 1,504 | 40 | 0.88s |
| Recursive summarization (compact every 15 turns) | 10/10 | 1,364 | 569 | 3.67s |
| Zone-based pruning (4 zones) | 10/10 | 1,651 | 40 | 0.9s |
