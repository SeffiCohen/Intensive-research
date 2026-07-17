# Phase 5 — Ideation report

Goal: `ideation-report.md` — the deliverable. Gate G3.

## Structure

1. **Landscape frame** (from `landscape.json`): size, growth, burst status,
   diversity, review pressure of the subject — 1 short section with numbers.
2. **The leaderboard** (from `leaderboard.md` / `gap-scores.json`): top
   `--top` gaps with GapScores and rank ranges. State explicitly that
   quantitative sub-scores are normalized within this gap set, and that a
   wide rank range means "statistical tie".
3. **Per-gap dossiers** for the top `--top` gaps, each containing:
   - the gap statement + type (taxonomy label);
   - **evidence of demand**: the supporting quotes with citation markers
     `[@id]{anchor=...}` — every marker must resolve against the corpus;
   - the metric scorecard (from `gap-metrics.json`) with one sentence
     interpreting the two most extreme metrics;
   - **survival note**: what the skeptic searched, what was closest to
     filling the gap, and why it survived (cite the near-miss papers —
     they are the related-work seed for whoever picks the gap up);
   - **proposed research questions** (from the judges' notes): 1-3 concrete,
     PICO-shaped where applicable, each with a one-line study/method sketch
     and the first dataset or instrument one would reach for;
   - judge rationales in one merged paragraph (attributed by seat, not
     re-averaged).
4. **Contested + refuted appendix**: contested gaps with their discount,
   refuted gaps with the papers that killed them — a refuted "gap" with its
   filling paper is itself useful output (it is a literature pointer).
5. **Candidate surplus appendix**: gaps beyond the tier cap, one line each.
6. **Coverage manifest + Run Receipt**: what was not searched (sources
   outside the API set, grey literature, non-English), window, ledger counts,
   cache hits, agents spawned.

## Gate G3 (code)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" audit-report \
  research/<slug>/ideation-report.md --corpus research/<slug>/corpus.json \
  --out research/<slug>/gate-report.json
```

Exit 1 blocks delivery: fix the markers (or drop the claim) and rerun. When
green, update `passport.yaml` (G3 pass) and `state.yaml` → `phase: done`,
then present the report path + leaderboard summary to the user. Offer
`scholar.py export` for the supporting corpus and `/ir-research` deep dives
on any single gap.
