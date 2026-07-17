# Phase 7 — Figures (opt-in, after compile)

Gated on: runtime present (or explicit deferred-OK), intensity ≥ intensive, and
user opt-in (`--figures`). Runs after Phase 6 compile.

This phase uses the SAME two agents and figure logic as paper-writing's
`phases/2.5-figures.md` and the same standards
(`${CLAUDE_PLUGIN_ROOT}/skills/paper-writing/references/figure-standards.md`) —
there is one figure implementation.

1. Probe: `scholar.py doctor --check-figures`.
2. Build anchored `figures/<id>.data.json` from the report's key results /
   synthesis; for a systematic review, `scholar.py emit-prisma` from the
   `search-ledger.jsonl` counts.
3. Spawn `ir-figure-designer` in ONE message (parallel Task calls, ≤8) → wait
   `.done` → spawn `ir-figure-critic` in ONE message (parallel) → loop
   revise→re-render up to the tier cap (1/2/3) → `figure-manifest.json`.
4. Gates: `ir-claim-auditor` anchors figure data (G2); re-run
   `audit-report --figure-manifest` (G3). Embed only rendered (`pass`) figures
   as results; deferred figures ship as separate artifacts.
5. `SendUserFile` the vector masters + PNG proofs. Record figure count in the
   passport budget block.
