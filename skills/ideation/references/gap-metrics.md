# Gap-ranking metrics

Why these metrics: each one operationalizes a validated signal from
bibliometrics, literature-based discovery, or research-prioritization
practice. Quantitative metrics are computed **deterministically in code**
(`scholar_metrics.py`, via `scholar.py gap-metrics`) from OpenAlex
aggregations; qualitative axes are judge-panel scores on anchored rubrics
(`gap-rubric.md`). Composite scoring and defaults live in
`scholar_metrics.DEFAULT_WEIGHTS` — code is the source of truth.

## Quantitative (0.50 of default weight)

| Metric (weight) | Formula / source | Why it ranks gaps well | Main caveat |
|---|---|---|---|
| **momentum** (.10) | Blend of smoothed-endpoint CAGR, OLS log-slope, 3-year recency share, and **Kleinberg burst detection** (Kleinberg 2003) of the gap's probe queries, with all-of-OpenAlex yearly counts as denominator so database growth is not read as a burst | A gap sitting in an accelerating neighborhood gets attacked (and funded) sooner; timing is part of a gap's value | Momentum also flags crowded frontiers — read it WITH headroom, not alone |
| **headroom** (.08) | `1 − minmax(log1p(total works matching probe queries))` | Direct opportunity signal: the same gap is worth more where the literature is thin — fewer competitors, more low-hanging fruit | A tiny literature can also mean a dead end or an infeasible problem; the panel's answerability axis balances this |
| **corroboration** (.15) | `minmax(√n_supporting × (0.5 + 0.5·recent_share))` over verified supporting papers | The strongest demand signal there is: independent author teams independently declaring the same hole (evidence-gap practice, Robinson et al. 2011). Recency-weighted — a gap last mentioned in 2015 may be quietly filled | Miners can only corroborate what the corpus contains; breadth of discovery bounds this metric |
| **bridge** (.07) | Swanson-style co-occurrence structure: Jaccard, containment, NPMI of the pair, and `bridge_opportunity = (1 − containment) × log-scaled size of the smaller side` | Literature-based discovery's core result (Swanson 1986): valuable findings hide in unconnected literatures; a big-A, big-B, empty-A∩B configuration is a discovery template | Some pairs are unlinked because the link is nonsense; the skeptic and the panel filter absurd bridges |
| **review_deficit** (.05) | `minmax(log1p(recent primary works per recent review))` | Many primaries + no recent synthesis = a systematic-review/meta-analysis opportunity, one of the most concrete future-work products a gap can imply | Counts OpenAlex `type:review`, which misses some survey venues |
| **accessibility** (.05) | `0.6 × OA share + 0.4 × (1 − minmax(venue HHI))` | Feasibility-of-entry proxy: open literatures are cheaper to build on; venue-dispersed fields are easier to publish into than oligopolies | Weak proxy — real feasibility (data, equipment, cohorts) is judged by the panel's answerability axis |

Also computed and reported (unweighted, context for judges and the report):
**Rao-Stirling diversity** (Stirling 2007) of the gap's topic neighborhood
over the OpenAlex topic hierarchy — high diversity suggests
interdisciplinary reach; the **sleeping-beauty coefficient** (Ke, Ferrara,
Radicchi & Flammini, PNAS 2015) is available in `scholar_metrics` for
dormant-paper analysis; **Price index** for reference recency.

## Qualitative (0.50 of default weight; judge panel, medians in code)

Axes adapted from CHNRI research-priority criteria (Rudan et al.) and the
rubric dimensions validated in LLM-ideation evaluation (Si, Yang & Hashimoto
2024 — where human experts found LLM ideas novel but weaker on feasibility,
which is why answerability is scored by a hostile methodologist seat, not
generated optimism):

| Axis (weight) | Question |
|---|---|
| **novelty** (.15) | Is the missing thing genuinely missing and non-obvious — or a well-known open problem already under heavy attack? |
| **importance** (.15) | If closed, what unblocks? Scientific reach + practical stakes (CHNRI: burden reduction / effectiveness) |
| **answerability** (.12) | Can a competent team make real progress in 2–3 years with plausibly obtainable data and methods? (CHNRI: answerability) |
| **actionability** (.08) | Does the gap translate into a concrete, well-posed study design tomorrow — or only into "study X more"? |

## Aggregation (in code — `score-gaps`)

- **Weighted geometric mean** × 100, sub-scores floored at 0.05. This is a
  deliberate departure from CHNRI's Research Priority Score, which is a
  weighted *arithmetic* mean and therefore fully compensatory — a weakness
  the MCDA literature (ISPOR task force) flags explicitly. Geometric
  aggregation means a gap near-zero on any core axis cannot win on the
  others; the 0.05 floor keeps a single zero from annihilating the product.
- **Panel agreement** (adapted from CHNRI's Average Expert Agreement) is
  computed in code from the judge panel's score spread and reported beside
  every rank: a top gap with low agreement is a judgment call, not a
  consensus, and the report must say so.
- Quantitative sub-scores are **min-max normalized across the run's gap
  set**: scores are relative to the sibling candidates, not absolute.
- **Survival multiplier** from the skeptic: survived ×1.0, contested ×0.6,
  refuted ×0 (excluded, listed separately).
- **Sensitivity**: every leaderboard reports each gap's rank range under
  ±25% one-at-a-time weight perturbation. Overlapping ranges = present as a
  tie; never oversell a rank the weights created.
- Custom weights via `score-gaps --weights <json>` (e.g. a user optimizing
  for PhD-feasible projects raises answerability); record the override in
  `passport.yaml`.

## Honest limits

Bibliometric signals lag reality by months (indexing delay) and say nothing
about unpublished/industrial work; probe queries are an imperfect proxy for
a gap's true neighborhood; normalization makes scores run-relative. The
metrics narrow attention; the verified quotes, skeptic evidence, and judge
rationales are the part a human should actually read before committing a
year of work.
