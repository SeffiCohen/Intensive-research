# Judge rubric — anchored 1-5 scales

Integers only. Score against the anchors, not your gut; cite in the
rationale the evidence (quote, metric, landscape fact) that moved you.
Panel medians are computed in code — never average seats yourself.

## novelty — is the missing thing genuinely missing and non-obvious?

- **1** — Not actually missing (you can name work that fills it) or trivially
  obvious next step every group is already taking.
- **2** — Well-known open problem, prominently flagged in multiple reviews;
  crowded frontier rather than a gap.
- **3** — Recognized but under-pursued; a few groups circling, no direct
  attack.
- **4** — Rarely articulated; supporting quotes exist but the combination /
  population / method angle is fresh (e.g. high bridge_opportunity).
- **5** — Nobody has stated it as a research target; emerges only from
  cross-paper patterns; skeptic's best attacks found nothing adjacent.

## importance — what unblocks if this gap is closed?

- **1** — Answer would change nothing beyond the papers that mentioned it.
- **2** — Incremental refinement of a niche result.
- **3** — Meaningful advance within one subfield; cited by its neighbors.
- **4** — Unblocks multiple lines of work or a real clinical/engineering/
  policy decision; several independent teams asked for it (corroboration).
- **5** — Field-level consequence: a standing assumption tested, a
  contradiction resolved, a missing benchmark the whole area would adopt.

## answerability — can real progress be made in 2–3 years?

- **1** — Unanswerable in principle or needs data/instruments that do not
  and will not exist (methodologist seat: be brutal here).
- **2** — Needs a consortium, decade-scale cohort, or restricted data most
  teams cannot obtain.
- **3** — Hard but plannable: nonstandard data acquisition or method
  development with known precedents.
- **4** — A competent group could design the study today; data plausibly
  obtainable (OA datasets, standard cohorts, simulation).
- **5** — Clear design with existing public data/methods; a strong PhD
  student could start Monday.

## actionability — does the gap convert into a well-posed study?

- **1** — Only "more research is needed on X"; no study falls out of it.
- **2** — Direction visible but the question resists operationalization
  (fuzzy constructs, no measurable outcome).
- **3** — Concrete question exists; design requires nontrivial choices with
  unclear tradeoffs.
- **4** — Question + design + outcome measures are nearly self-evident from
  the gap statement (PICO-expressible where applicable).
- **5** — Reads like the first paragraph of a grant: population, method,
  comparator, outcome, and first dataset all name themselves.

## Discipline

- The four axes are independent — a gap can be novelty 5 / answerability 1.
  Do not let one halo the others.
- Anchor 3 is the honest default under thin evidence; say "thin evidence"
  in the rationale when you use it.
- Novelty ratings must respect the skeptic file **when present** — panels
  usually run in parallel with the skeptics, so it often is not; in that
  case ground novelty ≥4 in the miners' near-miss notes instead, and rely
  on the survival multiplier (applied in code after both finish) to correct
  any inflation on gaps the skeptics later refute or contest.
- Bridge metrics with `weak_side: true` (a probe phrase that barely matches
  the literature) are unreliable — prefer the corpus observed-pattern
  evidence over them and say so in the rationale.
