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

## Retrieval backbone (`scripts/scholar.py`)

Stdlib-only Python, invoked everywhere as
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py"`.

```
scholar.py
├─ scholar_match.py  title normalize/similarity/exact-gate, id normalizers
├─ scholar_http.py   SQLite cache + cross-process rate buckets + degradation
└─ scholar_apis.py   10 adapters, normalize to the canonical paper schema
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
one budget. A bounded `Retry-After`/`x-ratelimit-reset` backoff (cap 30s) is
honored before a source is degraded. Dataset hosts are paced to verified limits
(Zenodo 30/min, Hugging Face 500/300s). **Caching** is a SQLite `http_cache`
with per-class TTLs (negative verdicts ≤48h so a fresh retraction is never
masked; positives 90d; search 7d; metadata 30d; dataset 14d) and a gate-version
+ schema-version stamp.

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
| **G2** | after drafting | 100% of claims audited (incl. figure-data anchoring); 0 MAJOR_DISTORTION / UNVERIFIABLE / inconsistent stats | claim-auditor + statistician |
| **G3** | before finalize | citation markers join to verified, non-retracted corpus entries (+ figure-manifest sync) | `audit-report` **exit code** |
| **G-D** | dataset stage | modality/license/ethics gates; unfit blocks, conditional needs sign-off | `datasets fitness --gate` **exit code** |
| **G4** | submission readiness | reporting-standard must-pass items + orphan-p scan + reproducibility + figure integrity + reviewer adequacy shards | `readiness` **exit code** ∧ `.done` shards |

## v2 subsystems

- **Venue style-learning**: `venue-sample` resolves a venue (OpenAlex source →
  Crossref ISSN → DBLP) and fetches recent exemplars (abstracts backfilled from
  Crossref); `style-profile` deterministically computes structure/length/citation
  -density/hedging statistics; `originality` is a verbatim-overlap screen. The
  `ir-style-analyst` never reads exemplar prose — only `style_profile.json`
  (numbers) crosses to the writer, and a leak-check asserts no source sentences
  leaked. This is the plagiarism firewall by construction.
- **Dataset discovery**: 8 dataset adapters (Hugging Face, OpenML, DataCite,
  Zenodo, UCI, NCBI GEO/SRA, OpenNeuro) normalize to a canonical DATASET-RECORD,
  collapsed across mirrors by shared DOI/conceptdoi (distinct from paper
  `INDEX_ANCESTRY`). `datasets fitness` scores nine criteria with three veto
  gates (modality, license, ethics/PII keyed off dataset content). No run/train/
  download-full verb exists — scholar.py structurally cannot fetch a dataset
  payload.
- **Figures**: `ir-figure-designer` renders (user runtime Python) a vector master
  + raster proof + an integrity `meta.json`; `ir-figure-critic` reads the PNG
  with vision and writes a machine-readable critique; the skill loops
  revise→re-render to a tier cap. `emit-prisma` produces a data-grounded PRISMA
  flow (DOT/SVG). All plotted values are anchored (audited at G2).
- **Submission-readiness**: a machine-readable checklist bank
  (`references/checklists/*.json`) drives `readiness`; regex/structural items are
  the exit code, `llm-judge` items delegate to reviewer `.done` adequacy shards.

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
