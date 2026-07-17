# Reporting standards & the submission-readiness gate (G4)

The quality substrate. A machine-readable checklist bank lives in
`references/checklists/*.json`; `scholar.py readiness` runs the auto-detectable
items and delegates the judgment items to reviewer agents.

## Study-type router

| Declared design | Checklist set (`--checklist-set`) |
|---|---|
| Systematic review / meta-analysis | `prisma-2020,frontmatter` |
| Randomized controlled trial | `consort,frontmatter` |
| Observational (cohort/case-control/cross-sectional) | `strobe,frontmatter` |
| Animal study | `arrive,frontmatter` |
| ML / computational | `neurips,frontmatter` |
| Dataset release | `datasheets,frontmatter` |
| Trained-model release | `model-card,frontmatter` |

Every submission also gets `frontmatter` (COI, funding, data/code availability,
ethics, abstract, references, limitations). The methodology reviewer declares
the design at Phase 0; the pipeline passes the matching set to `readiness`.

## How G4 scores (deterministic + delegated)

Each checklist item carries `auto_detectable ∈ {regex, structural, llm-judge}`
and `severity ∈ {must, should}`.

- **regex / structural** must-pass items → checked deterministically by
  `scholar.py readiness`; a miss makes the gate **exit nonzero**.
- **llm-judge** must-pass items → the responsible reviewer agent
  (`ir-methodology-reviewer`, `ir-statistician`, `ir-devils-advocate`,
  `ir-impact-reviewer`) writes an adequacy verdict to
  `readiness/<item-id>.done` (`adequate` / `inadequate: <reason>`). The skill
  passes G4 **iff** the readiness exit code is 0 **and** every required reviewer
  `.done` is `adequate`. Highest-stakes items require two-reviewer consensus
  (methodology + devil's advocate).

`readiness` also runs, deterministically: an **orphan-p-value scan** (a p-value
with no nearby effect size or CI → statistical-completeness fail), a **TOP-style
reproducibility** classification (data/code availability), a **figure-manifest
sync** (an embedded figure with `render_status ∈ {deferred, needs_human}` or a
`revise` critic verdict fails), and, in **proposal run-mode**, a block on any
populated Results section or past-tense results claim.

## Reproducibility (TOP)

Score Data / Code / Materials availability 0–3. A "results reproducible from the
released artifacts" claim requires an actual availability statement + link;
`readiness` flags a numeric result with no citation or data-file provenance.

## Pinned sources

Checklist `canonical_source_url`s point at stable PMC/journal/publisher URLs or
DOIs — never EQUATOR-network slugs (several 404). `doctor --check-standards`
HEAD-verifies them.
