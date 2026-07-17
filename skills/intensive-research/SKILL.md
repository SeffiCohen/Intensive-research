---
name: intensive-research
description: Tool-grounded multi-agent literature research. Spawns parallel searcher subagents that query OpenAlex, Crossref, arXiv, Europe PMC, PubMed, DBLP and OpenReview through the bundled scholar.py CLI (never from memory), screens with PRISMA discipline, verifies 100% of citations and screens retractions, then synthesizes an adversarially reviewed, fully cited report. Use for deep research, literature reviews, systematic reviews (PRISMA), fact-checking, or related-work scans. Do NOT use for quick single facts (use a normal answer) or for reviewing an existing draft (use peer-review).
argument-hint: "<question> [--mode research|lit-review|systematic-review|fact-check|brief] [--intensity standard|intensive|exhaustive]"
---

# Intensive Research — orchestrator

You are the research orchestrator. You do the planning and the fan-out; the real
work happens in parallel subagents whose output lands on disk. **Disk is the
interconnect**: subagents write full output to `research/<slug>/` and return
≤150-token summaries; you read shards from disk, never bloat your context with
full agent outputs.

## Step 0 — Preflight (always first)

Run the environment check and stop on hard failure:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor
```
If `IR_MAILTO` is unset, tell the user their polite-pool rate limits will be
throttled and Unpaywall full-text resolution is disabled, and suggest
`export IR_MAILTO=<email>`. Continue only if python + cache + network are OK.

## Step 1 — Scope & confirm

Parse `--mode` (default `research`) and `--intensity` (default `standard`).
`brief` mode = a single-pass answer with light verification, no subagent
fan-out — use it for small questions and skip to `phases/brief.md`.

For every other mode, read `references/intensity-levels.md`, compute the cost
estimate for the chosen tier, and **confirm scope + intensity with the user
before spawning any fleet**. Create `research/<slug>/`, write `passport.yaml`
from `templates/passport.yaml` (question, mode, intensity, inclusion criteria),
and initialize `state.yaml` (`phase: discovery`).

## Phase state machine

You advance through phases, re-reading the phase file at each boundary so long
runs survive context compaction. `state.yaml` records `phase`, gate statuses,
and artifact paths; a fresh session resumes from it.

| Phase | Instructions file | Gate |
|---|---|---|
| 1 discovery | `phases/1-discovery.md` | G1a |
| 2 screening | `phases/2-screening.md` | — |
| 3 verification | `phases/3-verification.md` | **G1b** |
| 4 analysis | `phases/4-analysis.md` | — |
| 5 synthesis + challenge | `phases/5-synthesis.md` | — |
| 6 compile + audit | `phases/6-compile.md` | **G2, G3** |

**Read the phase file before acting in that phase.** Do not hold all phase
instructions in context at once.

## Fan-out rule (the core of "intensive")

When a phase says "spawn N agents", spawn them in a **SINGLE message containing N
parallel Task tool calls** — never one at a time. Each Task prompt must contain
the labeled sections the phase file specifies (OBJECTIVE / WORKSPACE / OUTPUT
FILE / LEDGER / SOURCES / FLOOR / STOP / BOUNDARIES). Cap concurrency at 8; if a
tier needs more than 8, run them in back-to-back batches of ≤8.

Reconcile completion against `.done` marker files on disk (subagents run in the
background), not against notifications. When every expected shard/`.done` exists,
advance the phase in `state.yaml` and continue.

## Gates

Gates are defined in `references/passport-spec.md`. G1b and G3 are enforced by
`scholar.py` exit codes, not by agent assertions. A failing gate blocks the
next phase; record the reason in `passport.yaml` `gates` and continue only after
it passes (or the user overrides with recorded reasoning).

## Artifacts (all under `research/<slug>/`)

`passport.yaml`, `state.yaml`, `shards/`, `search-ledger.jsonl`, `corpus.json`,
`prisma.md`, `evidence/*.md`, `synthesis.md`, `challenge.md`, `report.md`,
`claim-audit.md`, `citation-verification.json`, `gate-report.json`.

The final `report.md` ends with a **Run Receipt** (from `passport.yaml.budget`)
and the **coverage manifest** (limitations). Offer exports via
`scholar.py export` (BibTeX/RIS/CSL-JSON) and `/ir-status <slug>` for a dashboard.
