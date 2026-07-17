---
name: paper-writing
description: Corpus-grounded academic writing. Drafts papers, sections, abstracts, or related-work from a verified research corpus (or triggers intensive-research to build one first), with outline checkpoints, parallel section writers, the machine-checkable citation marker grammar, and a claim audit before delivery. Use to write or revise a paper/section/abstract/related-work from research. Do NOT use for reviewing (peer-review) or pure literature research (intensive-research).
argument-hint: "<target: paper|section|abstract|related-work> [--from research/<slug>] [--venue name] [--figures] [--run-mode proposal|empirical] [--words N]"
---

# Paper Writing — orchestrator

You turn a verified corpus + synthesis into publishable prose. No corpus, no
prose: every citation must resolve to a verified corpus entry.

## Step 0 — Preflight + corpus

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor`.

- `--from research/<slug>` given → read its `passport.yaml`, `corpus.json`,
  `synthesis.md`, `evidence/`. If gates G1a/G1b are not `pass`, stop and tell
  the user which gate is open.
- No corpus → tell the user writing requires one and offer to run the
  intensive-research skill first (or `ingest` their own reference list into a
  corpus and verify it).
- `--run-mode` (default `empirical`): `proposal` forbids a Results section and
  past-tense results claims (for un-run experiments). `empirical` requires a
  provenance manifest + a human attestation that this plugin did not generate
  the data — the plugin never fabricates results.

## Step 0b — Venue calibration (if `--venue`)

Follow `phases/0-venue-calibration.md`: spawn `ir-style-analyst`, gate on
`style_profile.done`, and pass the profile's structural features (only) to the
writer. Exemplar prose never enters the writer's context.

## Step 1 — Outline (user checkpoint)

Draft the outline: sections, word budgets (from `--words` or the target's
norm), the claims each section will carry (mapped to synthesis entries), and
the register. **Show the user and get approval before drafting** — the outline
is the cheapest place to change direction.

## Step 2 — Draft (parallel where independent)

Spawn `intensive-research:ir-writer` per independent section batch (≤3 writers
in ONE message; sequential for interdependent sections):
```
SECTION(S): <name + outline slice + word budget>
INPUT: synthesis.md, evidence/*.md, corpus.json, passport.yaml
STYLE: ${CLAUDE_PLUGIN_ROOT}/skills/paper-writing/references/writing-guide.md
OUTPUT: drafts/<section>.md ; When finished: drafts/<section>.done
CONTRACT: [@corpus_id]{anchor=...} markers; corpus-only citations; no new claims.
```
Concatenate into `drafts/paper.md` (or the single target file). For
`abstract` / `related-work` targets, one writer suffices.

## Step 2.5 — Figures (if `--figures`)

Follow `phases/2.5-figures.md`: the render → critique → fix loop over anchored
`figures/*.data.json`, producing `figure-manifest.json`. Off by default.

## Step 3 — Audit + gates (G2, G3, style/originality, G4)

1. Spawn in ONE message: `intensive-research:ir-claim-auditor` and
   `intensive-research:ir-statistician` over the draft (pass bar: zero
   MAJOR_DISTORTION / UNVERIFIABLE / inconsistent; the auditor also anchors any
   figure data). 
2. Style + originality (if a profile was built): recompute draft style vs the
   profile envelope (soft guidance, never a hard block), then the HARD verbatim
   screen: `scholar.py originality --draft drafts/paper.md --against exemplar-manifest.json`
   — any flagged span blocks G3.
3. Deterministic citation gate (G3):
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" audit-report drafts/paper.md \
     --corpus <corpus.json> [--figure-manifest figure-manifest.json] --out drafts/gate-report.json
   ```
4. **Submission-readiness terminal gate (G4)** — the methodology reviewer
   declares the design → checklist set (`reporting-standards.md`), reviewers
   write adequacy `.done` shards, then:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" readiness --manuscript drafts/paper.md \
     --checklist-set <set> --run-mode <mode> [--figure-manifest ...] \
     --adequacy-shards drafts/readiness --out drafts/submission_readiness.json
   ```
   G4 passes iff readiness exits 0 AND every required reviewer `.done` is
   `adequate`. Fix-and-rerun each gate until it passes. Never deliver on a
   failing gate; a forced draft ships clearly marked DRAFT-UNAUDITED with the
   gate reports attached.

## Step 4 — Deliver

Hand over the draft + claim-audit + gate reports + submission-readiness
scorecard + figures (via `SendUserFile`) + export offer (`scholar.py export`).
Note evidence-depth caveats (claims on abstract-only sources) explicitly.
