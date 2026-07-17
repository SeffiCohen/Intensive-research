# Intensive Research

**Tool-grounded, retraction-aware, multi-agent academic research for Claude Code.**

Intensive Research turns a research question into a fully cited, adversarially
reviewed report by spawning **parallel subagents** that discover literature
through real scholarly APIs — never from model memory — screen it with PRISMA
discipline, **verify 100% of citations** across independent indexes, **screen
every source against the Retraction Watch database**, and audit every claim
against the source it cites. Integrity gates are enforced by **program exit
codes**, not by an agent's say-so.

Version 2.0.0 · License **CC BY-NC 4.0** · A derivative of
[academic-research-skills](https://github.com/Imbad0202/academic-research-skills)
(see [Attribution](#attribution)).

> **New in v2:** venue **style-learning** (learn a journal's structure, never
> copy its content), **dataset discovery + vetting** for experiments (license,
> ethics/PII, size, splits — never runs experiments or fabricates results),
> **publication-quality figures** with a render→vision-critique→fix loop, and a
> reporting-standard **submission-readiness gate** (PRISMA/CONSORT/STROBE/
> ARRIVE/NeurIPS/datasheets/model-cards).

> ⚠️ **NonCommercial license.** This project inherits CC BY-NC 4.0 from its
> upstream. The NC term likely restricts use inside a for-profit workplace —
> read the [license](LICENSE) before relying on it commercially.

---

## Why it's different

The problem with AI research assistants is that they *write* citations from
memory and *verify* them (maybe, sampled) later — which is exactly how
hallucinated references get into papers. Intensive Research inverts that:

- **Discovery is a tool, not a memory.** Every candidate paper is retrieved
  through a bundled CLI that queries OpenAlex, Crossref, arXiv, Europe PMC,
  PubMed, DBLP, and OpenReview. No paper enters the corpus unless an API
  returned it.
- **Verification happens at corpus-entry, at 100%.** Not sampled, not deferred.
  A reference that no index can resolve is flagged as possibly fabricated and
  blocks the gate.
- **Retractions are screened.** The full Retraction Watch database (~68k
  records) is loaded locally and joined against every cited DOI, backed by
  live Crossref update-to relations. Citing a retracted paper fails the gate.
- **Real parallel agents.** 12 specialized subagents fan out in parallel Task
  batches (searchers, screeners, analysts, a citation verifier, a claim
  auditor, a statistician, a review panel, a devil's advocate, a synthesizer,
  a writer) — not one model role-playing a committee in sequence.
- **Deterministic gates.** `scholar.py audit-report` extracts every citation
  marker, joins it to verification + retraction status, and **exits nonzero**
  on any uncited, unverified, or retracted citation. The gate is code.

## Install

```text
/plugin marketplace add SeffiCohen/Intensive-research
/plugin install intensive-research@intensive-research
```

Then run `/ir-setup` once (environment check + optional keys), or jump straight
to `/ir-research "your question"`.

**Prerequisites**

- Claude Code (recent version with plugin + subagent support).
- **Python 3.9+** on `PATH` (`python3` or `python`). Stdlib only — **no pip
  packages required** for the plugin itself.
- **`IR_MAILTO=<your email>`** (recommended): lifts OpenAlex/Crossref rate
  limits and is **required for Unpaywall** full-text resolution. Everything
  else works keyless.
- Optional: `NCBI_API_KEY` (PubMed 3→10 rps), `S2_API_KEY` (adds Semantic
  Scholar as a third verification vote).

Cross-platform: rate limiting and caching use SQLite (no `fcntl`), so
concurrent subagents coordinate correctly on **Linux, macOS, and Windows**.

## Commands

| Command | What it does |
|---|---|
| `/ir-research <q> [--mode ...] [--intensity ...]` | Multi-agent literature research (`research`, `lit-review`, `systematic-review`, `fact-check`, `brief`) |
| `/ir-verify <file-or-claim>` | Citation audit of a document, or fact-check of a claim |
| `/ir-write <target> [--from research/<slug>]` | Corpus-grounded paper / section / abstract / related-work |
| `/ir-review <file> [--intensity ...]` | Parallel peer-review panel + editorial decision |
| `/ir-pipeline <topic> [--intensity ...]` | End-to-end: research → write → review → revise → final gate |
| `/ir-datasets <goal> [--modality ...]` | Discover, rank, and vet datasets for a proposed experiment (never runs them) |
| `/ir-figures <slug> [--journal ...]` | Publication-quality figures with a render→critique→fix loop |
| `/ir-readiness <file> [--design ...]` | Submission-readiness gate: reporting standards, stats, reproducibility, figures |
| `/ir-status [slug] [--clean <slug>]` | Run dashboard: gates, PRISMA counts, budget, resume point |
| `/ir-export <corpus> [--format ...]` | BibTeX / RIS / CSV / CSL-JSON export (Zotero-importable) |
| `/ir-watch <research/<slug>>` | Living review: new papers + **new retractions** since the run |
| `/ir-setup` | Environment check, keys, permission allowlist |
| `/ir-help` | Command overview + intensity dial |

## The intensity dial

One setting scales breadth — **never** integrity. Verification and claim audits
are always 100%.

| | `standard` | `intensive` | `exhaustive` |
|---|---|---|---|
| Parallel searchers | 2 | 4 | 6–8 (≤3 waves) |
| Source floor | 25 | 50 | 100+ |
| Screening | 1 screener | dual + adjudicator | dual + adjudicator |
| Full-text analysis | top 8–10 | top-K + pivotal | all included |
| Citation verification | **100%** | **100%** | **100%** |
| Claim audit | **100%** | **100%** | **100%** |
| Review panel | 3 seats | 5 seats | 5 seats |
| Venue style exemplars | 3 | 5 | 8 |
| Datasets vetted | top-3 | top-5 | top-10 |
| Figure critique loop | 1 round | 2 | 3 |

Verification, claim audits, figure-data anchoring, dataset license/ethics gates,
and must-pass reporting-checklist items are **always full strength** — intensity
scales breadth, never integrity. Multi-agent runs cost roughly an order of
magnitude more tokens than a single answer; the skill shows a per-tier estimate
and confirms scope before spawning the fleet. Every report ends with a **Run
Receipt** (agents spawned, API calls, cache hits, wall time) and a **coverage
manifest** listing what was *not* searched.

## What it does NOT do (deliberate v1 scope-outs)

Honest boundaries beat overclaiming:

- **Never runs experiments or fabricates data/results.** It discovers, vets, and
  ranks datasets and *proposes* experiment protocols; running them (and honestly
  attesting to the provenance) is the human's job. Proposal mode structurally
  blocks any Results section for an un-run experiment.
- **Learns venue style as statistics only** — section structure, length, citation
  density — and never copies exemplar content (a hard verbatim screen blocks the
  gate on any copied span).
- **Figures need your runtime Python** (matplotlib/pillow; graphviz for
  schematics). Without them, figures ship as spec + runnable code + caption — the
  plugin never fakes a rendered figure.
- **Sources without a free, ToS-clean API**: books/monographs, theses & grey
  literature, patents, standards, clinical-trial registries, non-English-only
  databases (e.g. CNKI), subscription indexes (Scopus, Web of Science), and
  **Google Scholar** (no API; automation violates its ToS). The `exhaustive`
  tier emits a manual Google-Scholar checklist and can re-ingest DOIs you find.
- No GUI screening, no vector-RAG over your PDF library, no scite-scale citation
  stance corpus, no paywalled full text.
- No authoring tail (rebuttals, submission packaging) — that pairs well with the
  upstream [ARS](https://github.com/Imbad0202/academic-research-skills) suite.

## Attribution

Intensive Research is a derivative work of **Academic Research Skills (ARS)**
v3.17.0, © 2026 **Cheng-I Wu**, licensed CC BY-NC 4.0. It reuses ARS's title-
similarity matching, PRISMA/AI-disclosure protocol, source-quality hierarchy,
reviewer rubrics, and the Material Passport concept, and rebuilds everything
else. Full detail and the list of adapted files: [NOTICE.md](NOTICE.md).
Distributed under the same [CC BY-NC 4.0](LICENSE) license.

Retraction data: [Retraction Watch](https://retractionwatch.com/) /
Crossref Labs. Scholarly metadata: OpenAlex, Crossref, arXiv, Europe PMC,
NCBI/PubMed, DBLP, OpenReview, Unpaywall, OpenCitations, DOAJ. Dataset metadata:
Hugging Face, OpenML, DataCite, Zenodo, UCI ML Repository, NCBI GEO/SRA,
OpenNeuro. Reporting standards are cited and linked (PRISMA, CONSORT, STROBE,
ARRIVE, NeurIPS, Datasheets for Datasets, Model Cards), never reproduced.

**AI is a copilot, not the pilot.** This tool handles retrieval, verification,
and the grunt work; you define the question, judge the evidence, and own the
conclusions.
