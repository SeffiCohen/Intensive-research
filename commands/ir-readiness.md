---
description: Submission-readiness gate (G4) — check a manuscript against reporting standards, reproducibility, statistics, and figure integrity
argument-hint: "<file> [--design systematic-review|rct|observational|animal|ml|dataset|model] [--from research/<slug>]"
disable-model-invocation: true
---

Run the submission-readiness gate on: $ARGUMENTS

Determine the study design → checklist set (see
`${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/references/reporting-standards.md`),
then run:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" readiness --manuscript <file> \
  --checklist-set <set> --run-mode <proposal|empirical> [--figure-manifest ...] \
  [--adequacy-shards <dir>] --out submission_readiness.json
```
For the `llm-judge` checklist items, spawn the responsible reviewer agents
(methodology / statistician / devil's-advocate / impact) to write adequacy
`.done` shards. Report the scorecard: missing must-pass items, orphan p-values,
reproducibility statements, figure-integrity failures, and the overall verdict
(pass iff the gate exits 0 AND every required reviewer verdict is `adequate`).
