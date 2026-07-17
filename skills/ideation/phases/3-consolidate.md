# Phase 3 — Consolidation + verification

Goal: one clean `gaps.json` of distinct, verified candidate gaps. Gate G1b.

## 1. Cluster duplicate gaps (you)

Read all `gaps-raw/*.json`. Merge gaps that state the same missing thing
(same unstudied population, same unbenchmarked method, same unlinked pair)
even when worded differently:

- The merged gap keeps the clearest statement, the **union of supporting
  papers** (this is what powers the corroboration metric — independent papers
  pointing at the same hole is the strongest demand signal), the union of
  probe queries (cap 3, keep the most specific), and the most specific type.
- `bridge.a`/`bridge.b` must be short searchable phrases (2–4 words, the
  literature's own vocabulary, no slashes) — `gap-metrics` uses them verbatim
  as search terms, and a label that matches no works zeroes the bridge
  signal. Sanity-probe each side with `scholar.py count '"<phrase>"'`.
- Assign stable ids `G01…Gnn`, ordered by supporting-paper count descending.
- Cap the **statement-mined** set at the tier's gap cap (ideation-levels.md);
  Channel B structural bridge nominations are additive on top, up to the
  tier's bridge row. Surplus goes to an appendix list in the report, not
  silent truncation.
- **Preprint/published pairs**: the corpus dedup can miss a preprint and its
  published version when years differ by >1 (e.g. an arXiv DOI and a venue
  DOI with the same title). Count such a pair as ONE supporting paper — keep
  the published id — so corroboration is never inflated by the same work
  twice.

Write `research/<slug>/gaps.json` per `templates/gaps-schema.json`.

## 2. Verify supporting papers — gate G1b (code)

Build the set of all supporting paper ids, extract those records from
`corpus.json` into `research/<slug>/gap-support.json`, and run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" verify-batch \
  --in research/<slug>/gap-support.json --strict \
  --out research/<slug>/gap-support-verified.json
```

On exit 1: remove the failing papers from every gap's `supporting` list. A gap
with zero surviving support is deleted (record it in `passport.yaml` under
`dropped_gaps` with the reason). Retracted support is always removed — a gap
"corroborated" by a retracted paper is not corroborated.

Update `passport.yaml` (G1b status, gap count) and `state.yaml` →
`phase: scoring`.
