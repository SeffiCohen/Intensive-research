---
description: Living-review update — re-run a past run's logged queries, diff the corpus for new papers and NEW RETRACTIONS
argument-hint: "<research/<slug>>"
disable-model-invocation: true
---

Arguments: $ARGUMENTS

For the given run directory:

1. Read `search-ledger.jsonl`; collect the distinct (query, sources) pairs.
2. Re-run each via
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" search "<q>" --sources <s> --fresh --out research/<slug>/watch/new-<n>.json`
   then `dedup` the watch shards together.
3. Diff against `corpus.json` (by cluster id): report NEW papers since the run.
4. Retraction sweep on the EXISTING corpus:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" verify-batch --in research/<slug>/corpus.json --out research/<slug>/corpus.json --fresh`
   and report any citation whose retraction status changed — that is the
   highest-value alert a living review can give.
5. Summarize: new candidate papers (titles + ids), retraction changes, and
   whether the report's conclusions look affected (offer a targeted re-run of
   screening/synthesis for the new papers).
