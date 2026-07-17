# Architecture

## Orchestration model

Skills orchestrate; subagents do the work; **disk is the interconnect.**

```
main session (a SKILL.md phase state machine)
│  reads phases/<n>.md at each boundary  ── compaction-proof
│  spawns subagents in parallel Task batches (≤8 concurrent)
│  reconciles completion via .done marker files on disk
│
├─ ir-searcher × N ──► shards/facet-*.json   + search-ledger.jsonl
├─ ir-screener × 1-2 ─► shards/screen-*.json  (PRISMA reason codes)
├─ ir-analyst × N ───► evidence/<id>.md       (anchored extraction)
├─ ir-citation-verifier ─► citation-verification.json
├─ ir-claim-auditor / ir-statistician ─► claim-audit.* / stats-review.md
├─ review panel (methodology/domain/impact/statistician/devils-advocate) ─► reviews/*.md
├─ ir-synthesizer ──► synthesis.md
└─ ir-writer ───────► report.md  (citation markers)

every subagent returns ≤150 tokens (summary + path + counts);
the orchestrator never ingests full agent output — it reads shards from disk.
```

Subagents *can* nest in current Claude Code, but the orchestrator lives in the
main session on purpose: the user sees the plan, and permission prompts surface
at the top level rather than buried in a background agent.

State lives in `research/<slug>/state.yaml` (phase, gates, artifact paths). A
fresh session resumes by reading it; `/ir-status` reports the resume point.

## Ideation subsystem (`skills/ideation`)

`/ir-ideate <subject>` runs the same orchestration model with a different
product: a ranked leaderboard of research gaps. Pipeline:

```
1 landscape   topic-trends CLI: growth/burst/diversity frame + searcher fan-out (G1a)
2 gap mining  ir-gap-miner × N over corpus chunks (quote-anchored gap statements)
              + orchestrator-nominated Swanson bridge candidates
3 consolidate merge duplicate gaps (union of supporting papers = corroboration)
              verify-batch --strict over all supporting papers (G1b)
4 scoring     gap-metrics CLI (deterministic bibliometrics, ~10-15 calls/gap)
              ∥ ir-gap-judge × 3 seats (rubric 1-5; medians computed in code)
              ∥ ir-gap-skeptic × per gap (fresh searches try to kill the gap)
              score-gaps --require-survival (G4: exit 1 on missing verdict)
5 report      per-gap dossiers + audit-report gate (G3)
```

Ranking doctrine: quantitative sub-scores (momentum, headroom, corroboration,
bridge, review deficit, accessibility) are min-max normalized across the gap
set; qualitative axes (novelty, importance, answerability, actionability)
come from judge medians; the composite is a weighted **geometric** mean ×100
with a survival multiplier (contested ×0.6, refuted excluded), and every
leaderboard carries a ±25% weight-perturbation rank range. Formulas live in
`scripts/scholar_metrics.py` (Kleinberg burst vs whole-database denominator,
Rao-Stirling over the OpenAlex topic hierarchy, NPMI/containment bridge
stats, sleeping-beauty coefficient); rationale in
`skills/ideation/references/gap-metrics.md`.

## Retrieval backbone (`scripts/scholar.py`)

Stdlib-only Python, invoked everywhere as
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py"`.

```
scholar.py
├─ scholar_match.py    title normalize/similarity/exact-gate, id normalizers
├─ scholar_http.py     SQLite cache + cross-process rate buckets + degradation
├─ scholar_apis.py     10 adapters, normalize to the canonical paper schema
└─ scholar_metrics.py  gap-ranking bibliometrics (pure math + OpenAlex aggregations)
```

**Adapters:** OpenAlex (primary — widest coverage, abstracts, citation graph),
Crossref (metadata + update-to relations), arXiv, Europe PMC (biomed + OA full
text), PubMed E-utilities (MeSH + Retracted-Publication signal), DBLP,
OpenReview, Unpaywall (OA PDF resolver), OpenCitations (independent citation
edges), and optional Semantic Scholar (a third vote, `S2_API_KEY` only). DOAJ
backs the screener's venue-quality lane.

**Rate limiting** is a SQLite `rate_limits` table updated under `BEGIN
IMMEDIATE` with `busy_timeout` — portable to Windows and genuinely shared across
every concurrent subagent process, so 8 searchers hitting OpenAlex stay inside
one budget. **Caching** is a SQLite `http_cache` with per-class TTLs (negative
verdicts ≤48h so a fresh retraction is never masked; positives 90d; search 7d;
metadata 30d) and a gate-version + schema-version stamp.

**Degradation contract:** `fetch()` never raises for network/HTTP conditions;
it returns a result with a `degraded_reason`. A single API outage degrades that
source (`per_source[...].status = degraded`) and never aborts the fan-out.

### Canonical paper schema

```json
{"id","ids":{"doi","arxiv","openalex","pmid","pmcid","dblp","s2","openreview"},
 "title","authors","year","venue","type","abstract","abstract_source",
 "cited_by_count","is_oa","oa_pdf_url","urls",
 "retraction":{"status","source","checked_at"},
 "provenance":{"source_apis","query","retrieved_at"},
 "verification":{"status","indexes_agreed","independent_count","checked_at"}}
```

## Integrity gates

| Gate | When | Check | Enforcement |
|---|---|---|---|
| **G1a** | identification | every record has API provenance or a resolved snowball lookup | orchestrator |
| **G1b** | after screening | 100% of *included* verified; fabricated/retracted block | `verify-batch` |
| **G2** | after drafting | 100% of claims audited; 0 MAJOR_DISTORTION / UNVERIFIABLE / inconsistent stats | claim-auditor + statistician |
| **G3** | before finalize | citation markers join to verified, non-retracted corpus entries | `audit-report` **exit code** |
| **G4** | ideation ranking | every ranked gap carries a skeptic survival verdict; refuted gaps excluded, contested ×0.6 | `score-gaps --require-survival` **exit code** |

**Verification semantics.** An ID-keyed lookup (DOI/arXiv/PMID + exact-
normalized-title cross-check) resolving in one authoritative index →
`verified`. Title-only matches need ≥2 **independent** indexes, counted against
an index-ancestry map (OpenAlex re-ingests Crossref/arXiv/PubMed, so
OpenAlex+Crossref = one confirmation, not two). `not_found` only on an id-keyed
miss; a non-exact title-only match is `unresolvable` (human-review queue), never
an auto-block. Correction/erratum/retraction-notice titles never match the base
work.

**Retraction gate.** `retraction.status ∈ {none, retracted, correction, eoc,
withdrawal, unknown}` — an enum, never a boolean. Sourced from the local
Retraction Watch database (bulk-loaded, refreshed weekly) and live Crossref
update-to relations, with OpenAlex/PubMed signals as corroboration. G3 re-checks
cited DOIs on a 48h cache class so a stale cache cannot hide a new retraction.

## Full-text acquisition

Waterfall (stdlib only; `scholar.py` never parses PDFs):
Europe PMC JATS XML → arXiv PDF → Unpaywall best-OA-location PDF downloaded to
`research/<slug>/fulltext/`. `ir-analyst` reads downloaded PDFs with Claude's
native PDF-capable Read tool and declares its read scope per paper
(`full_text` / `sections` / `abstract_only`), so abstract-only support surfaces
as `UNVERIFIABLE_ACCESS` rather than false full-text confidence.

## PRISMA provenance

Identification (per-source hit counts logged to `search-ledger.jsonl`) →
dedup by DOI→arXiv→PMID→title+year with OpenAlex clustering, counting *clusters*
→ screening (reason codes) → eligibility (verification on the included set) →
inclusion. `prisma.md` renders the flow counts and a saturation curve; the
`passport.yaml` coverage manifest states what was not searched. Every report
carries the AI-disclosure block.

## What was intentionally not carried from upstream

ARS's ~100 CI hash-lock validators, sprint-contract/cross-model schemas,
MODE_REGISTRY, the phase-scope PreToolUse guard, and the temporal-sidecar
subsystem (reduced here to a stdlib temporal lint inside `audit-report`). The
result is ~60 files instead of 1104, with the token budget spent on breadth and
verification instead of governance bookkeeping.
