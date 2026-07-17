---
name: peer-review
description: Multi-agent peer-review panel. Spawns 3-7 differentiated reviewer subagents in parallel (methodology, domain, impact, statistician, devil's advocate) with pre-committed scoring contracts, adjudicates disagreements, and renders an editorial decision with a prioritized revision list. Use to review a paper, draft, or report like a program committee. Do NOT use for writing (paper-writing) or literature research (intensive-research).
argument-hint: "<file> [--intensity standard|intensive|exhaustive] [--mode panel|single|rebuttal-check]"
---

# Peer Review — panel orchestrator

You orchestrate an independent review panel. Reviewers work in parallel and
never see each other's reviews; you synthesize and decide.

## Step 0 — Setup

- Locate the manuscript file the user named. Create `reviews/` next to it (or
  under `research/<slug>/reviews/` if reviewing a pipeline report).
- Read `${CLAUDE_PLUGIN_ROOT}/skills/peer-review/references/review-protocol.md`
  and `references/rubrics.md`. Determine the panel for the tier
  (standard 3 / intensive 5 / exhaustive 7 seats — see protocol).
- `--mode single`: one methodology-reviewer pass only, for a quick rubric take.
- `--mode rebuttal-check`: follow protocol §Rebuttal-check with the rebuttal +
  prior reviews the user supplies.

## Step 1 — Spawn the ENTIRE panel in ONE message (parallel Task calls)

Subagent types: `intensive-research:ir-methodology-reviewer`,
`intensive-research:ir-domain-reviewer` (spawn prompt names the specific field;
at exhaustive, a second domain seat gets a different sub-field persona),
`intensive-research:ir-impact-reviewer`, and at intensive+:
`intensive-research:ir-statistician`, `intensive-research:ir-devils-advocate`;
at exhaustive also `intensive-research:ir-claim-auditor` (if a corpus exists).

Every Task prompt contains:
```
MANUSCRIPT: <path>
RUBRIC: ${CLAUDE_PLUGIN_ROOT}/skills/peer-review/references/rubrics.md
OUTPUT: reviews/<seat>.md
SPRINT CONTRACT: state your scoring criteria BEFORE reading the manuscript.
INDEPENDENCE: do not read other reviews.
When finished, create reviews/<seat>.done
```
Cap 8 concurrent; wait for all `.done` markers (respawn a dead seat once).

## Step 2 — Synthesize and decide

Follow protocol §Synthesis: tabulate scores, adjudicate >20-point divergences
and P0 conflicts as structured disagreements (never silent averaging), compute
the weighted aggregate, and write `reviews/meta-review.md` with the decision
(Accept / Minor / Major / Reject), the score table, adjudications, and a
deduplicated P0→P2 revision list.

## Step 3 — Revision loops (optional, bounded)

Only while aggregate < 80 or a P0 is open, up to the tier's loop cap
(1/2/3); each loop pre-commits which findings it addresses; re-review is a
narrow pass. Early-stop on <3-point movement with no P0.

## Step 2.5 — Submission-readiness gate (G4)

After the decision, run the readiness gate so "ready" means "meets the venue's
reporting bar", not just "reviewers liked it". The methodology reviewer declares
the study design → checklist set
(`${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/references/reporting-standards.md`);
reviewers write adequacy `.done` shards for the `llm-judge` items into
`reviews/readiness/`:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" readiness --manuscript <file> \
  --checklist-set <set> --run-mode <mode> [--figure-manifest ...] \
  --adequacy-shards reviews/readiness --out reviews/submission_readiness.json
```
G4 passes iff readiness exits 0 AND every required reviewer `.done` is
`adequate` (highest-stakes items need methodology + devil's-advocate consensus).
Emit a `reviews/submission_readiness.md` scorecard.

Report to the user: decision, aggregate score, submission-readiness verdict,
top concerns, and the `reviews/` paths.
