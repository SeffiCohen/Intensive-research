---
name: paper-writing
description: Corpus-grounded academic writing. Drafts papers, sections, abstracts, or related-work from a verified research corpus (or triggers intensive-research to build one first), with outline checkpoints, parallel section writers, the machine-checkable citation marker grammar, and a claim audit before delivery. Use to write or revise a paper/section/abstract/related-work from research. Do NOT use for reviewing (peer-review) or pure literature research (intensive-research).
argument-hint: "<target: paper|section|abstract|related-work> [--from research/<slug>] [--words N]"
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

## Step 3 — Audit before delivery (Gate G2 + G3)

Spawn in ONE message: `intensive-research:ir-claim-auditor` and
`intensive-research:ir-statistician` over the draft (pass bar: zero
MAJOR_DISTORTION / UNVERIFIABLE / inconsistent). Then run the deterministic
gate yourself:
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" audit-report drafts/paper.md \
  --corpus <corpus.json> --out drafts/gate-report.json
```
Fix-and-rerun until exit 0. Never deliver on a failing gate; if the user wants
the draft anyway, deliver it clearly marked DRAFT-UNAUDITED with the gate
report attached.

## Step 4 — Deliver

Hand over the draft + claim-audit summary + gate report + export offer
(`scholar.py export` for the reference manager). Note evidence-depth caveats
(claims resting on abstract-only sources) explicitly.
