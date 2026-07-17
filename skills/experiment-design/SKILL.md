---
name: experiment-design
description: Dataset discovery and experiment planning. Finds, ranks, and vets the best datasets for a proposed experiment across Hugging Face, OpenML, DataCite, Zenodo, and UCI (license, ethics/PII, size, splits, provenance), then produces a PROPOSED protocol. Never runs experiments or fabricates results. Use to choose datasets and design an experiment. Do NOT use to execute or write up experiments.
argument-hint: "<experiment goal> [--modality m] [--intensity standard|intensive|exhaustive]"
---

# Experiment Design — dataset discovery + protocol proposal

You help choose datasets and design an experiment. This skill **terminates at
"protocol proposed"** — it has no execution phase. It never runs, trains,
downloads a corpus, or emits a result.

## Step 0 — Preflight + spec

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor`. Elicit and
write `experiment-spec.json`:
```
{task, modality, target_metric, required_splits[], min_size,
 usage{commercial, redistribution, derivatives},
 ethics_constraints{human_subjects, pii_ok}, domain, run_mode: "proposal"}
```
`run_mode` starts as `proposal` and is threaded to paper-writing/readiness so no
results section or past-tense result can be written for an un-run experiment.

## Step 1 — Dataset discovery (spawn the scout)

Spawn `intensive-research:ir-dataset-scout` (if >1, in ONE message with parallel
Task calls):
```
EXPERIMENT-SPEC: experiment-spec.json
WORKSPACE: research/<slug>/
OUTPUT: dataset-candidates.json + dataset-fitness.json + passport dataset block
INTENSITY: <tier: top-3/5/10 shortlist vetted>
When finished: research/<slug>/dataset-scout.done
```

## Step 2 — Gate G-D (dataset integrity)

Run the deterministic gate:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" datasets fitness \
  --candidates research/<slug>/dataset-candidates.json \
  --spec research/<slug>/experiment-spec.json --gate --out research/<slug>/dataset-fitness.json
```
- `unfit` (a gate vetoed: modality mismatch / incompatible license /
  human-subjects PII without ethics) → excluded; report why.
- `conditional` (unknown license or unverified ethics) → requires an explicit
  human sign-off; re-run with `--signoff` only after the user confirms.
- `fit` → eligible.
See `${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/references/dataset-quality.md`.

## Step 3 — Proposed protocol (no execution)

Emit a ranked dataset shortlist + a datasheet-completeness note + a **PROPOSED,
NOT EXECUTED** experiment protocol (task, chosen dataset(s) + license/access,
splits, metric, baselines to compare, planned analysis, threats to validity).
Stamp it `PROPOSED PROTOCOL — NO EXPERIMENT PERFORMED`. Record the dataset
provenance (license, access, ethics flags) into the Material Passport.

Hand off: if the user later runs the experiment themselves, `paper-writing` in
`empirical` run-mode requires a provenance manifest + their attestation that
this plugin did not generate the data. See `references/experiment-design.md`.
