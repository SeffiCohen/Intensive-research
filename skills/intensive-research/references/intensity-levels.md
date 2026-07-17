# Intensity levels (single source of truth)

Every skill reads this table. Intensity scales **search breadth and panel
size** — it NEVER reduces verification or claim-audit coverage, which are always
100% of the included/cited set.

| Parameter | `standard` | `intensive` | `exhaustive` |
|---|---|---|---|
| Parallel searchers (wave 1) | 2 | 4 | 6–8 |
| Search waves (max) | 1 | 2 | 3 |
| Total searcher spawns (cap) | 2 | 6 | 12 |
| Query floor / source floor | ≥6 queries / ≥3 sources | ≥15 / ≥5 | ≥30 / ≥7 |
| Corpus floor (post-dedup clusters) | 25 | 50 | 100 |
| Corpus cap (included) | 80 | 150 | 250 |
| Snowballing | refs of top 5 | refs+cites of top 10 | until <10% new/round |
| Screening | 1 screener | 2 screeners + adjudicator | 2 screeners + adjudicator |
| Full-text analysis | top 8–10 | top-K + all pivotal/contradicted | all included |
| **Citation existence (G1b)** | **100% of included** | **100%** | **100%** |
| **Claim audit (G2)** | **100% of claims** | **100%** | **100%** |
| Reviewer panel (differentiated seats) | 3 | 5 | 5 |
| Devil's-advocate refutations / claim | 1 | 2 | 3 |
| Revision loops (only if below pass bar) | 1 | 2 | 3 |
| Venue style sample (recent exemplars) | 3 | 5 | 8 |
| Dataset candidates vetted (experiment-design) | top-3 | top-5 | top-10 |
| Figure critique-loop cap (with `--figures`) | 1 | 2 | 3 |
| Reporting-standard checklist depth | must-pass | full | full |
| Concurrency (parallel Tasks at once) | ≤8 | ≤8 | ≤8 |

## Hard caps (never exceeded regardless of tier)

- ≤ 3 search waves, ≤ 12 total searcher spawns, ≤ 250 included papers
  (surplus goes to an annotated appendix, not silent truncation).
- ≤ 8 concurrent Task spawns in any single fan-out batch.
- Revision loops 2–3 run ONLY if a reviewer scores below the rubric pass bar;
  early-stop when a round changes the aggregate score by < 3 points with no P0.
- Figures are OFF by default in `standard`; the figure critique loop is capped
  at 1/2/3 rounds.
- **Not tier-scaled (fixed at 100% / full strength regardless of intensity):**
  citation existence (G1b), claim audit (G2), figure-data anchoring, must-pass
  reporting-checklist items (G4), dataset license/ethics/modality gates (G-D),
  and the verbatim-originality screen. Intensity scales breadth, never integrity.

## Coverage floors are checked, not assumed

The orchestrator reads `search-ledger.jsonl` and refuses to advance past
discovery until the query and source floors for the tier are met. Report the
actual counts in `prisma.md`.

## Cost estimate (shown before any intensive/exhaustive fan-out)

Multi-agent research costs roughly an order of magnitude more tokens than a
single-pass answer. Before launching, compute and show the user an estimate:

```
searchers × (~4–8k tok) + screeners + analysts×(full-text) + panel×(~6–10k)
+ verify/audit (API calls, ~0 model tok) ≈ <tier estimate>
```

- `standard`  ≈ a few dollars of model tokens; minutes of wall time.
- `intensive` ≈ several times that.
- `exhaustive` ≈ another several times that; can run tens of minutes (arXiv
  paces at 1 request/3s, so wide arXiv sweeps dominate wall time).

Always confirm scope + intensity with the user before spawning the fleet.
