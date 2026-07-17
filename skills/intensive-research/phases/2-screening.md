# Phase 2 — Screening (PRISMA)

Goal: an included set with an auditable exclusion tally.

## 1. Abstract fallback

Records missing abstracts get the fallback chain (playbook §abstract fallback):
the screener handles per-record lookups, but if >30% of candidates lack
abstracts, run a batch enrichment first: for each DOI,
`scholar.py lookup --doi <doi>` (cached, cheap).

## 2. Spawn screeners (ONE message, parallel Task calls)

`subagent_type: intensive-research:ir-screener`.

- `standard`: 1 screener over the full candidate file.
- `intensive`/`exhaustive`: 2 INDEPENDENT screeners over the SAME records
  (not halves) — spawn both in one message. Each Task prompt contains:

```
CRITERIA: <inclusion/exclusion from passport.yaml, verbatim>
INPUT: research/<slug>/corpus-candidates.json
OUTPUT FILE: research/<slug>/shards/screen-<a|b>.json
INTENSITY: <tier>  (no-abstract rule applies at intensive/exhaustive)
When finished, create research/<slug>/shards/screen-<a|b>.done
```

## 3. Adjudicate (intensive/exhaustive)

Compare the two decision files. Agreements stand. For disagreements, YOU act as
the adjudicator: re-read the record against the criteria and decide, recording
`adjudicated: true` and the disagreement rate in the PRISMA counts. Never
resolve by averaging.

## 4. Retraction & venue lane

Excluded-with-reason records keep their reason codes (`RETRACTED`,
`VENUE_QUALITY`, ...). Verify the screener applied the retraction rule to every
record whose `retraction.status` is `retracted`/`withdrawal`.

## 5. Emit

Write `research/<slug>/corpus.json` = included (+`unclear` flagged) records.
Update `passport.yaml` `corpus_summary` (included, excluded_by_reason,
unclear_no_abstract) and `prisma.md` screening counts from
`templates/prisma-flow.md`. `state.yaml` → `phase: verification`.
