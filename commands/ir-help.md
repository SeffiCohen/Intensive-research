---
description: Intensive Research — command overview, intensity dial, environment variables
argument-hint: ""
disable-model-invocation: true
---

Show the user this overview (rendered, with any environment-specific notes from
a quick `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor --json`):

## Commands

| Command | What it does |
|---|---|
| `/ir-research <q> [--mode ...] [--intensity ...]` | Multi-agent literature research (research, lit-review, systematic-review, fact-check, brief) |
| `/ir-verify <file-or-claim>` | Citation audit of a document, or fact-check of a claim |
| `/ir-write <target> [--from research/<slug>]` | Corpus-grounded paper/section/abstract writing |
| `/ir-review <file> [--intensity ...]` | Parallel peer-review panel + editorial decision |
| `/ir-pipeline <topic> [--intensity ...]` | End-to-end: research → write → review → revise → final gate |
| `/ir-datasets <goal> [--modality ...]` | Discover, rank, and vet datasets for a proposed experiment |
| `/ir-figures <slug> [--journal ...]` | Publication-quality figures with a render→critique→fix loop |
| `/ir-readiness <file> [--design ...]` | Submission-readiness gate (reporting standards, stats, figures) |
| `/ir-status [slug] [--clean <slug>]` | Run dashboard: gates, PRISMA, budget, resume point |
| `/ir-export <corpus> [--format ...]` | BibTeX / RIS / CSV / CSL-JSON export |
| `/ir-watch <research/slug>` | Living review: new papers + NEW RETRACTIONS since the run |
| `/ir-setup` | Environment check, keys, permission allowlist |
| `/ir-help` | This overview |

## Intensity dial

`standard` (2 searchers, 25-source floor, 3-seat panel) → `intensive` (4, 50,
5 seats, dual screening) → `exhaustive` (6–8 searchers ≤3 waves, 100+ sources,
all-included full text). Verification and claim audits are ALWAYS 100% —
intensity scales breadth, never integrity. Details:
`${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/references/intensity-levels.md`.

## Environment

- `IR_MAILTO` — polite-pool email (recommended; required for Unpaywall)
- `NCBI_API_KEY`, `S2_API_KEY` — optional rate/coverage upgrades
- `IR_CACHE_DIR` — cache location override
- Everything works keyless; sources degrade per-API, never fatally.
