---
name: ideation
description: Academic ideation engine. Takes a subject, maps its research landscape through scholarly APIs, mines candidate research gaps from the actual literature (never from model memory), then ranks them with deterministic bibliometric metrics plus a judge panel — every top gap adversarially checked against fresh searches to confirm it is not already filled. Use to find and prioritize future-work directions, thesis topics, grant angles, or review-paper opportunities. Do NOT use for answering a research question (use intensive-research) or reviewing a draft (use peer-review).
argument-hint: "<subject> [--intensity standard|intensive|exhaustive] [--window <years>] [--top <k>]"
---

# Ideation — orchestrator

You are the ideation orchestrator. The product is a **ranked leaderboard of
research gaps** worth addressing in future work, each one grounded in cited,
verified papers and scored on transparent metrics. Disk is the interconnect:
subagents write shards under `research/<slug>/` and return ≤150-token
summaries; you read shards from disk.

Two failure modes this skill exists to prevent, in priority order:

1. **Fabricated gaps** — a "gap" supported by papers that don't exist, or by
   nothing at all. Countered by corpus provenance (G1a) + 100% verification of
   supporting papers (G1b).
2. **Already-filled gaps** — the classic LLM-ideation failure: proposing work
   that exists. Countered by the skeptic survival gate (G4): every ranked gap
   is attacked with fresh targeted searches before it may appear in the
   leaderboard.

## Step 0 — Preflight

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor
```
Stop on hard failure. If `IR_MAILTO` is unset, warn (throttled rate limits).

## Step 1 — Scope & confirm

Parse arguments: subject, `--intensity` (default `standard`), `--window`
years (default 12), `--top` leaderboard depth (default 10). Read
`references/ideation-levels.md` for the tier table, show the user the scope +
cost estimate, and **confirm before spawning any fleet**. Create
`research/<slug>/` (slug from the subject + `-ideation`), write `passport.yaml`
(subject, intensity, window, date) and `state.yaml` (`phase: landscape`).

## Phase state machine

Advance phase by phase, re-reading each phase file at its boundary; record
progress in `state.yaml` so a fresh session can resume.

| Phase | Instructions file | Gate |
|---|---|---|
| 1 landscape + discovery | `phases/1-landscape.md` | G1a |
| 2 gap mining | `phases/2-gap-mining.md` | — |
| 3 consolidation + verification | `phases/3-consolidate.md` | **G1b** |
| 4 metrics + panel + survival | `phases/4-scoring.md` | **G4** |
| 5 report | `phases/5-report.md` | **G3** |

## Fan-out rule

When a phase says "spawn N agents", spawn them in a SINGLE message of N
parallel Task calls, ≤8 concurrent; reconcile against `.done` marker files on
disk, respawn a dead agent once. Never paste shard contents into your context
— read counts and top entries only.

## Gates (code-enforced where possible)

- **G1a** — every corpus record has API provenance (scholar.py output always
  does).
- **G1b** — 100% of gap-supporting papers verified via
  `scholar.py verify-batch --strict`; a gap citing an unverifiable or
  retracted paper loses that support (and dies if no support remains).
- **G4 (survival)** — `scholar.py score-gaps --require-survival` **exits 1**
  if any ranked gap lacks a skeptic verdict. Refuted gaps are excluded,
  contested gaps discounted ×0.6 — multipliers live in code, not prose.
- **G3** — the final report's citation markers must join to the verified
  corpus: `scholar.py audit-report` exit code.

## Ranking doctrine (read once, apply in phase 4)

Metric definitions and formulas: `references/gap-metrics.md`. Judge rubric
anchors: `references/gap-rubric.md`. Composite = weighted **geometric** mean
(a near-zero core criterion cannot be compensated away), panel medians are
computed **in code** (`rubric_to_scores`), and every leaderboard carries a
±25% weight-perturbation rank range — a rank that survives perturbation is a
signal; one that doesn't is presented as a tie.

## Artifacts (all under `research/<slug>/`)

`passport.yaml`, `state.yaml`, `landscape.json`, `shards/`,
`search-ledger.jsonl`, `corpus.json`, `gaps-raw/*.json`, `gaps.json`,
`gap-metrics.json`, `rubric/*.json`, `rubric.json`, `survival/*.json`,
`survival.json`, `gap-scores.json`, `leaderboard.md`, `ideation-report.md`.

The final report ends with a **Run Receipt** and a **coverage manifest**
(what was not searched, per `references/ideation-levels.md`).
