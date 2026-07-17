---
description: Discover, rank, and vet the best datasets for a proposed experiment (license, ethics/PII, size, splits) — never runs experiments
argument-hint: "<task/goal> [--modality m] [--sources hf,openml,datacite,zenodo,uci] [--intensity ...]"
disable-model-invocation: true
---

Run the `experiment-design` skill with: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/experiment-design/SKILL.md`: build an
experiment spec, spawn `ir-dataset-scout` to search Hugging Face / OpenML /
DataCite / Zenodo / UCI, run the deterministic fitness gate (G-D: license,
ethics/PII, modality), and emit a ranked shortlist + a PROPOSED protocol. The
plugin discovers and vets datasets only — it never downloads payloads, runs
experiments, or fabricates results.
