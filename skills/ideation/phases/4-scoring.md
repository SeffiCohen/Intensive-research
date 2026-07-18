# Phase 4 — Metrics, judge panel, survival checks

Goal: every gap scored on the full metric battery; every gap skeptic-checked.
Gate G4.

## 1. Deterministic bibliometrics (code, ~10-15 API calls per gap, cached)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" gap-metrics \
  --gaps research/<slug>/gaps.json --corpus research/<slug>/corpus.json \
  --year-from <window start> --year-to <current year> \
  --ledger research/<slug>/search-ledger.jsonl \
  --out research/<slug>/gap-metrics.json
```

This computes per gap: momentum (CAGR, log-slope, Kleinberg burst against
whole-database growth, 3-year recency share), crowding (works count, venue
HHI), accessibility (OA share), review deficit, bridge co-occurrence stats
(Jaccard / containment / NPMI / bridge_opportunity), Rao-Stirling topic
diversity, and corroboration structure. Definitions and caveats:
`references/gap-metrics.md`. Skim the output for gaps whose probe queries
degraded (`degraded` fields) — rerun those with `--fresh` once if needed.

## 2. Judge panel (parallel — spawn together with step 3)

Spawn **3 `intensive-research:ir-gap-judge`** agents in the same message as
the skeptics below — one per persona seat: `methodologist`, `domain-scholar`,
`impact-assessor`. Each scores ALL gaps independently:

```
OBJECTIVE: score all candidate gaps for subject "<subject>" — seat <persona>
WORKSPACE: research/<slug>/
INPUTS: gaps.json, gap-metrics.json (may exceed one read — page through it),
  landscape.json. The skeptic files do not exist yet (skeptics run in
  parallel with you); ground novelty in the miners' near-miss notes.
RUBRIC: ${CLAUDE_PLUGIN_ROOT}/skills/ideation/references/gap-rubric.md
OUTPUT FILE: research/<slug>/rubric/judge-<persona>.json
BOUNDARIES: score every gap on all four axes with 1-2 sentence rationales;
  propose 1-2 concrete research questions for gaps you rate importance ≥4.
When finished, create research/<slug>/rubric/judge-<persona>.done
```

When all three are done, merge WITHOUT averaging yourself: build
`research/<slug>/rubric.json` as
`{"gaps": {"G01": {"novelty": [j1, j2, j3], "importance": [...], ...}}}` —
per-axis **lists** in seat order. `score-gaps` takes the median in code.
Carry each judge's rationales and proposed questions along in the same file
under `"notes"` (ignored by the scorer, used by the report).

## 3. Skeptic survival checks (parallel with step 2)

One `intensive-research:ir-gap-skeptic` per gap (batches of ≤8 alongside the
judges; at `standard` you may give a skeptic up to 3 gaps):

```
OBJECTIVE: try to KILL gap <gap_id> — prove it is already filled
WORKSPACE: research/<slug>/
GAP: <statement + probe queries + supporting ids>
OUTPUT FILE: research/<slug>/survival/<gap_id>.json
LEDGER FILE: research/<slug>/search-ledger.jsonl
BOUNDARIES: verdict must rest on papers retrieved through scholar.py in THIS
  run; attach the killing papers' ids for refuted/contested verdicts.
When finished, create research/<slug>/survival/<gap_id>.done
```

Merge all `survival/*.json` into `research/<slug>/survival.json`
(`{"gaps": {"G01": {"verdict": ..., "reason": ..., "evidence": [...]}}}`).
Evidence entries with `role: restater` are fresh demand evidence the miners
never saw — carry them into the report's corroboration line for that gap
("+N independent restatements found during the survival check").

## 4. Composite scoring — gate G4 (code)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" score-gaps \
  --metrics research/<slug>/gap-metrics.json \
  --rubric research/<slug>/rubric.json \
  --survival research/<slug>/survival.json \
  --require-survival \
  --out research/<slug>/gap-scores.json \
  --leaderboard research/<slug>/leaderboard.md
```

`--require-survival` exits 1 if any gap lacks a skeptic verdict — respawn the
missing skeptic, never hand-write a verdict. Custom priorities (e.g. the user
cares most about feasibility) go through `--weights <file>`, recorded in
`passport.yaml`.

## 5. Top-of-table tie-break (when rank ranges overlap at the top)

Absolute LLM scores are noisy; pairwise comparison is the better-validated
protocol (Si, Yang & Hashimoto 2024 — their pairwise judge beat absolute
scoring on expert-labeled idea pairs). If the top 3–5 gaps' `rank_min`–
`rank_max` ranges overlap, spawn ONE extra `ir-gap-judge` Task (seat
`tie-break`) that compares only those gaps **pairwise** — for each adjacent
pair, which gap is the better use of a research year, one sentence why —
and record the pairwise order in `research/<slug>/rubric/tiebreak.json`.
The GapScores do NOT change; the report presents the tied cluster in
pairwise order with the judge's sentences. Never present a rank created by
weight noise as a real distinction.

Update `state.yaml` → `phase: report`.
