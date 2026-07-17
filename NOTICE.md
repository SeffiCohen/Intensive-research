# Notice of Attribution

**Intensive Research** is a derivative work of
[Academic Research Skills (ARS)](https://github.com/Imbad0202/academic-research-skills)
v3.17.0, copyright (c) 2026 **Cheng-I Wu**, licensed under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).

This project is distributed under the same license (see [LICENSE](LICENSE)).
It is a substantially restructured rebuild, not a fork: the retrieval layer,
agent roster, orchestration model, gate tooling, and most prose are new.
The following components are adapted from ARS and retain its ideas or text:

| File in this repo | Derived from (ARS path) | Nature of derivation |
|---|---|---|
| `scripts/scholar_match.py` | `scripts/_text_similarity.py` | Title normalization, similarity threshold (0.70), dotted-acronym pre-pass, exact-normalized-title gate, generic-title set — near-verbatim adaptation |
| `scripts/scholar_http.py` | `scripts/verification_cache.py`, `scripts/*_client.py` | SQLite cache + TTL pattern; 429 budget-exhaustion signal, backoff, narrow exception handling, host allowlist patterns |
| `skills/intensive-research/references/prisma-protocol.md` | `shared/prisma_trAIce_protocol.md`, `deep-research/references/systematic_review_protocol.md` | Condensed PRISMA + AI-disclosure items |
| `skills/intensive-research/references/source-quality.md` | `deep-research/references/source_quality_hierarchy.md` | Condensed source-quality hierarchy |
| `skills/intensive-research/templates/prisma-flow.md` | `deep-research/templates/prisma_report_template.md` | Flow-diagram counts template |
| `skills/peer-review/references/rubrics.md` | `academic-paper-reviewer/references/quality_rubrics.md` | Scoring dimensions, weights, decision bands |
| `skills/peer-review/references/review-protocol.md` | `academic-paper-reviewer/references/editorial_decision_standards.md`, `sprint_contract_protocol.md` | Decision standards; "sprint-contract-lite" concept |
| Claim-audit verdict taxonomy (`agents/ir-claim-auditor.md`) | ARS v3.8 claim-faithfulness audit classes | Verdict taxonomy concept |
| Temporal lint failure modes (`scripts/scholar.py`, auditor/devil's-advocate prompts) | ARS v3.9.4 temporal integrity verification | Failure-mode taxonomy, reduced to a stdlib lint |
| Material Passport concept (`references/passport-spec.md`) | `shared/handoff_schemas.md` Schema 9 | Provenance-ledger concept, heavily simplified |

Changes made (per CC BY-NC 4.0 §3(a)(1)(B)): discovery rebuilt on live scholarly
APIs instead of model memory; verification moved to corpus-entry time and made
deterministic (exit codes); retraction screening added; sequential personas
replaced by parallel Claude Code subagents; governance/CI machinery removed;
all orchestration, agents, commands, and skills rewritten.

## New in v2 (original to Intensive Research)

These capabilities are **not** derived from ARS; they are original to this
project: venue style-learning (`scholar.py venue-sample`/`style-profile`/
`originality` + `ir-style-analyst`), dataset discovery and vetting
(`scholar.py datasets` + `ir-dataset-scout` + the `experiment-design` skill),
the publication-figure subsystem (`ir-figure-designer`/`ir-figure-critic` +
`emit-prisma`), and the reporting-standard submission-readiness gate
(`scholar.py readiness` + the checklist bank). The claim-audit distortion
taxonomy and temporal-lint concepts remain adapted from ARS (above).

## Metadata-source acknowledgments

Scholarly metadata: OpenAlex, Crossref, arXiv, Europe PMC, NCBI/PubMed, DBLP,
OpenReview, Unpaywall, OpenCitations, DOAJ. Dataset metadata: Hugging Face Hub,
OpenML, DataCite, Zenodo, UCI ML Repository, NCBI GEO/SRA, OpenNeuro. Retraction
data: Retraction Watch / Crossref Labs. Reporting-standard checklists store a
paraphrased `requirement_text` plus a `canonical_source_url` to the original
(PRISMA 2020, CONSORT, STROBE, ARRIVE 2.0, NeurIPS checklist, Datasheets for
Datasets, Model Cards) — cited and linked, not reproduced. Environment figure
guidance skills (CC BY 4.0) are referenced with attribution.

**NonCommercial notice:** CC BY-NC 4.0 restricts commercial use. If you need
this tooling in a commercial setting, consult the license and the upstream
author's terms.
