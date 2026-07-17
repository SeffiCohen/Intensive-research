# Ideation intensity levels

Intensity scales breadth — corpus size, miner count, candidate volume. It
NEVER scales integrity: supporting-paper verification (G1b), skeptic coverage
of every ranked gap (G4), and report citation audit (G3) are always 100%.

| Parameter | `standard` | `intensive` | `exhaustive` |
|---|---|---|---|
| Searcher facets (wave 1) | 3 | 5 | 7–8 |
| Search waves (max) | 1 | 2 | 3 |
| Corpus floor (post-dedup) | 40 | 80 | 150 |
| Full text acquired for reviews | top 3 | top 6 | top 10 |
| Gap miners | 2–3 | 4–6 | 6–8 |
| Per-miner candidate floor | 5 | 5 | 6 |
| Candidate gap cap (post-merge) | 12 | 20 | 30 |
| Structural bridge candidates | 3 | 4–5 | 6 |
| Judge panel seats | 3 | 3 | 3 |
| **Skeptic coverage** | **100% of gaps** | **100%** | **100%** |
| Skeptic killer queries / gap | ≥4 | ≥6 | ≥8 |
| Leaderboard depth (default `--top`) | 10 | 12 | 15 |
| Concurrency (parallel Tasks) | ≤8 | ≤8 | ≤8 |

## Hard caps

- ≤3 search waves, ≤12 searcher spawns, ≤30 candidate gaps ranked (surplus →
  appendix, never silent truncation), ≤8 concurrent Tasks.
- `gap-metrics` probe queries: ≤3 per gap (enforced in code).

## Cost estimate (show before confirming scope)

```
searchers × (~4-8k tok) + miners × (~6-10k) + 3 judges × (~8-12k)
+ skeptics × (~4-6k each, one per gap) + report (~10k)
+ gap-metrics/score-gaps (API calls, ~0 model tok)
```

- `standard` ≈ a few dollars of model tokens; ~10–20 min wall time.
- `intensive` ≈ 2–3×; `exhaustive` ≈ 5×+ (full-text reads dominate).

## Coverage manifest (always in the report)

Sources not searched: books/monographs, theses, patents, clinical-trial
registries, subscription indexes (Scopus/WoS), Google Scholar, non-English
databases. Gaps that live only in those literatures will be missed; say so.
