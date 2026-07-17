# PRISMA 2020 protocol (+ AI-disclosure)

Condensed from PRISMA 2020 and ARS's `prisma_trAIce_protocol.md` (see NOTICE.md).
Used by the `systematic-review` mode and, in lighter form, by all discovery.

## The four stages (each emits auditable counts)

1. **Identification** — run every source search on a fixed date; log each query
   and its per-source hit count to `search-ledger.jsonl` (scholar.py `--ledger`
   does this for free). Deduplicate by DOI → arXiv → PMID → title+year, using
   OpenAlex clustering as a merge oracle; count merged **clusters**, and record
   the duplicate count. This is Gate G1a.
2. **Screening** — title/abstract screen against the passport criteria; record
   the number excluded per reason code. No record is excluded on title alone
   when no abstract could be obtained (→ retrieve-or-flag queue).
3. **Eligibility** — full-text assessment of screened-in records; record the
   number excluded at full text **with a reason for each**. Verification
   (Gate G1b) runs here, on the eligible set, at 100%.
4. **Inclusion** — the final study set → extraction (ir-analyst) → synthesis.

Emit the flow-diagram counts to `prisma.md` (template: `templates/prisma-flow.md`):
records identified (per source) → duplicates removed → screened → excluded at
screen (by reason) → assessed for eligibility → excluded at full text (by
reason) → included. Plus a **saturation curve** (new unique papers per wave,
from the ledger) and a stated coverage estimate.

## Reproducibility log (systematic-review mode)

Record: the exact search strings, the sources and their access date, the
inclusion/exclusion criteria, the dedup rule, and every exclusion reason. A
second person (or a fresh session) must be able to reproduce the included set
from this log alone.

## Risk of bias

For included studies, apply the appropriate instrument from
`appraisal-instruments.md` (RoB 2 / Newcastle-Ottawa / GRADE / AMSTAR 2) via the
methodology reviewer or statistician, and report a traffic-light summary.

## AI-disclosure (mandatory items)

Every report produced by this pipeline carries an AI-assistance disclosure:

- **Tools & role**: this pipeline (Intensive Research) performed literature
  discovery, screening support, citation verification, and drafting assistance;
  the human directed the question, criteria, interpretation, and conclusions.
- **Retrieval grounding**: all cited works were retrieved and existence-verified
  through scholarly APIs, not generated from model memory.
- **Verification coverage**: state the G1b/G2/G3 gate results and the
  evidence-depth breakdown (full-text vs abstract-only).
- **Limitations**: include the coverage manifest (sources not searched) verbatim.
- **No fabricated data**: this pipeline runs no experiments and generates no
  results; any experimental provenance is the human's, declared separately.
