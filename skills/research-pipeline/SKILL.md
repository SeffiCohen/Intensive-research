---
name: research-pipeline
description: End-to-end pipeline chaining research, writing, and review — intensive-research → paper-writing → peer-review → bounded revision loops → final citation gate — refusing to advance past any failing integrity gate. One intensity dial forwarded to every stage. Use for "research and write me a paper/report on X, reviewed". Do NOT use for a single stage (call that skill directly).
argument-hint: "<topic> [--intensity standard|intensive|exhaustive] [--target paper|report]"
---

# Research Pipeline — end-to-end orchestrator

You chain the three skills with gate checks between stages. The passport is the
spine; a failing gate stops the advance, always.

## Step 0 — Preflight + confirm

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor`. Read
`${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/references/intensity-levels.md`,
show the user the FULL-pipeline cost estimate for the tier (research + writing
+ panel + loops), and confirm scope + intensity before starting.

## Stages

| Stage | Skill | Advance only if |
|---|---|---|
| 1 Research | intensive-research (mode research or systematic-review) | G1a, G1b = pass |
| 2 Write | paper-writing (`--from research/<slug>`) | G2 = pass, audit-report exit 0 |
| 3 Review | peer-review (panel per tier) | decision rendered |
| 4 Revise | paper-writing revision of P0/P1 items | loop cap per tier; re-review narrow |
| 5 Final gate | `scholar.py audit-report` on the final text (G3) | exit 0 |
| 6 Deliver | — | — |

Between every stage: re-read `research/<slug>/passport.yaml` and `state.yaml`.
If the previous stage's gate is not `pass`, DO NOT advance — report what is
open and either fix within that stage's rules or stop for the user. Never mark
a gate from memory; gates G1b/G3 are `scholar.py` exit codes.

## Stage transitions (context hygiene)

Each stage is run by invoking that skill's SKILL.md flow, which re-reads its
own phase files. Keep your own context lean: carry forward only the slug, the
gate statuses, and artifact paths — everything else lives on disk.

## Revision loop rule

Loops run only while the review aggregate < 80 or a P0 is open, up to the
tier cap (1/2/3). Each loop pre-commits which findings it addresses; re-review
is narrow (open items + regression scan). Early-stop on <3-point movement with
no P0. Structured disagreements from review carry into the final report —
surfaced, never silently dropped.

## Deliver

Final report/paper + `reviews/meta-review.md` + `gate-report.json` + PRISMA
flow + Run Receipt + coverage manifest + export offer. Tell the user how to
extend later: `/ir-status <slug>` (dashboard), `/ir-watch <slug>` (living
review diff).
