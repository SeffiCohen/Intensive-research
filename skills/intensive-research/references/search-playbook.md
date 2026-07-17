# Search playbook

How searchers turn a facet into real papers. All retrieval goes through
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py"`.

## Wide → narrow

Start with 2–4 word queries to map the landscape, read what vocabulary the top
hits use, then narrow. Long hyper-specific queries first return nothing. Mirror
how an expert searches: broad, orient, focus.

## Source routing by domain

| Domain | Sources (`--sources`) | Why |
|---|---|---|
| CS / ML / AI / stats | `openalex,arxiv,dblp,openreview,crossref` | arXiv preprints, DBLP venues, OpenReview reviews |
| Biomedical / life sci | `europepmc,pubmed,openalex,crossref` | MEDLINE + PMC full text + MeSH |
| Physics / math | `arxiv,openalex,crossref` | arXiv is primary |
| Social sci / econ | `openalex,crossref` | broad coverage |
| Interdisciplinary / unsure | `openalex,crossref` + one domain source | OpenAlex is the widest single index |

OpenAlex is the primary index everywhere (widest coverage, abstracts, citation
graph). Crossref is the metadata authority. Give sibling searchers **distinct**
source groups so arXiv's 1-request/3s pacing doesn't serialize the fleet.

## Snowballing (citation chaining)

Once the central papers are identified:

- **Backward** (foundational): `scholar.py refs --doi <doi>` — what it builds on.
- **Forward** (newer): `scholar.py cites --openalex <id> --limit 30` — what
  builds on it.

At `exhaustive`, snowball until a round adds < 10% new unique papers.

## Adaptive waves

Wave-2+ queries are derived from wave-1 **included** papers: their keywords,
their reference lists, and the screener's feedback on what was missing. Don't
re-run wave-1 queries; extend the frontier.

## Abstract fallback chain

OpenAlex lost many Springer/Elsevier abstracts after Nov 2024. Before screening,
if a record lacks an abstract, the screener/`scholar.py lookup` tries, in order:
OpenAlex inverted index → Crossref → Europe PMC → PubMed EFetch → (S2 if keyed)
→ arXiv. Record `abstract_source`. A record with no obtainable abstract is never
excluded on title alone at intensive/exhaustive.

## Saturation & floors

Stop a facet when its source/query floor for the tier
(`intensity-levels.md`) is met AND two consecutive distinct queries each add
< 10% new unique papers. Log the saturation point. The orchestrator checks the
ledger against the floors before advancing.

## What the APIs do NOT cover

Books, theses, grey literature, patents, standards, clinical-trial registries,
subscription-only indexes (Scopus, Web of Science), and Google Scholar (no API;
ToS prohibits automation). These go in the coverage manifest. At `exhaustive`,
emit a human-in-the-loop checklist: run the top-3 ledger queries in Google
Scholar manually and feed unique DOIs back via `scholar.py ingest`.
