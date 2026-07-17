---
description: Dashboard for a research run — gates, PRISMA counts, verification coverage, budget, resume point (add --clean <slug> to remove intermediates)
argument-hint: "[research/<slug>] [--clean <slug>]"
disable-model-invocation: true
---

Arguments: $ARGUMENTS

1. No slug given → list the directories under `research/` with their
   `state.yaml` phase, and ask which to inspect (or show all one-liners).
2. For the chosen slug, read `passport.yaml` + `state.yaml` +
   `search-ledger.jsonl` tail, and run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" cache stats`.
   Present: question, mode/intensity, current phase + resume point, gate
   statuses (G1a/G1b/G2/G3), PRISMA counts, verification summary
   (verified/single-index/fabricated/retracted), evidence-depth tally, budget
   block (agents, API requests, cache hits), degradations, and artifact paths.
3. `--clean <slug>` → after showing what will be removed and confirming with
   the user, delete intermediates (`shards/`, `fulltext/`, `drafts/*.done`)
   while KEEPING `report.md`, `prisma.md`, `passport.yaml`, `corpus.json`,
   `reviews/`, `gate-report.json`.
