# Experiment design — spec, protocol, and the no-execution boundary

## experiment-spec.json

```json
{
  "task": "text-classification",
  "modality": "text",
  "target_metric": "macro-F1",
  "required_splits": ["train", "validation", "test"],
  "min_size": 10000,
  "usage": {"commercial": false, "redistribution": true, "derivatives": true},
  "ethics_constraints": {"human_subjects": false, "pii_ok": false},
  "domain": "nlp",
  "run_mode": "proposal"
}
```

## Proposed-protocol template

```
# Proposed experiment protocol — PROPOSED, NOT EXECUTED
Task: <task> · Metric: <target_metric>
Dataset(s): <record_id> — license <spdx> (open? NC? ND?), access <right>,
            size <n>, splits <...>, fitness <verdict>
Baselines: <list — to be compared, not yet run>
Planned analysis: <stats, significance test, effect size, CIs>
Threats to validity: <leakage, contamination, distribution shift, ...>
Ethics: <human-subjects/PII status, DUA/consent terms captured>
```

## The no-execution boundary (structural, not prose)

- `scholar.py datasets` has **no** run / train / download-full verb — it fetches
  only allowlisted metadata/card hosts. `download_urls[]` + checksums are
  recorded as metadata and never retrieved.
- `ir-dataset-scout` may run `scholar.py` (it needs a shell like every worker)
  but has no training/eval capability and is prompt-bound to never download a
  payload or emit an un-run result.
- This skill has no execution phase; it ends at "protocol proposed".
- `readiness --run-mode proposal` fails on any populated Results/Findings section
  or past-tense results claim, and stamps every page `PROPOSED PROTOCOL — NO
  EXPERIMENT PERFORMED`.

## Empirical run-mode (if the user ran the experiment themselves)

`paper-writing --run-mode empirical` requires:
- a provenance manifest describing how the data/results were produced, and
- an explicit human attestation that **this plugin did not generate the data or
  results**.
Every numeric result must then carry `{value, corpus_id|data_file, quote|page}`
provenance; unanchored numbers fail readiness. The plugin still runs no
experiments — it only helps report ones the human ran.
