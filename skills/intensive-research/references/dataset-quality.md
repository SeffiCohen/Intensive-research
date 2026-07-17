# Dataset quality & fitness (Gate G-D)

How `scholar.py datasets fitness` vets a dataset against an experiment spec. The
rule everywhere: **signal and flag, never certify.** Absent evidence is
`unverified`, never `pass`.

## Nine criteria (three are veto gates)

| # | Criterion | Type | Veto condition |
|---|---|---|---|
| 1 | Task / modality match | **gate** | affirmative modality mismatch |
| 2 | Size adequacy | weighted | — |
| 3 | Splits present | weighted | — |
| 4 | License vs usage rights | **gate** | affirmative NC vs commercial, or ND vs derivative |
| 5 | Provenance / citations | weighted | — |
| 6 | Leakage / contamination | weighted (signal-and-flag) | — |
| 7 | Ethics / consent / PII | **gate** | human-subjects/PII signal with NO ethics statement |
| 8 | Format / accessibility | weighted | — |
| 9 | Datasheet availability | weighted | — |

Weighted criteria (2,3,5,6,8,9) form a 0–100 aggregate; the three gates are
pass/veto. Verdict: `unfit` (any veto) → `conditional` (unknown license OR
present-but-unverified ethics — needs human sign-off) → `fit`.

## License calibration (avoid over-rejection)

- **Unknown / absent** license → `conditional` + review flag, **not** a veto.
  DataCite `rightsList` is frequently empty; a missing field is not a
  prohibition. Prefer HF/Zenodo/OpenML license fields over DataCite when a
  mirror provides one.
- **Hard veto** only on an *affirmative* NonCommercial license when
  `spec.usage.commercial`, or NoDerivatives when `spec.usage.derivatives`.

## Ethics / PII (keys off dataset CONTENT, not just the spec)

Gate 7 turns ON regardless of the experiment spec when the dataset itself
signals human subjects: a sensitive modality (`face`, `medical`, `clinical`,
`biometric`, `speech`, `location-trace`, `genomic`, `mri`, `eeg`) or domain;
PII-like feature/column names (name, email, dob, ssn, address, patient,
demographic, race, gender); or PII terms in the card. Then:

- ethics/consent statement **absent** → veto (`unfit`);
- **present but unverified** → `conditional` + surfaced flag (never `fit`).

Capture the specific DUA/consent terms into the Material Passport dataset block.

## Datasheets-for-datasets completeness

Prefer datasets with a datasheet or Croissant record (motivation, composition,
collection, consent/PII, preprocessing, license, known biases). Missing →
lower score, not a veto (see `checklists/datasheets.json`).

## The no-execution boundary

`scholar.py datasets` records `download_urls[]` + checksums as **metadata only**
and has no run/train/download-full verb — it structurally cannot fetch or
execute a dataset payload. The scout discovers, ranks, and vets; it never runs
experiments or emits results. G-D verifies the run tree contains no
payload-sized files.
