# Phase 6 — Compile + audit (Gates G2, G3)

Goal: the final report, certified by the claim audit and the deterministic
citation gate.

## 1. Write (ir-writer)

Spawn `intensive-research:ir-writer`:
```
INPUT: synthesis.md, challenge.md adjudications, evidence/*.md, passport.yaml
OUTPUT: research/<slug>/report.md
CONTRACT: every citation uses [@corpus_id]{anchor=...}; corpus-only citations;
structured-disagreement sections carried into the report; absolute dates.
When finished: research/<slug>/shards/write.done
```
For long reports with independent sections, spawn ≤3 writer instances on
disjoint sections in one message, then concatenate.

## 2. Audit fan-out (ONE message, parallel Task calls)

- `intensive-research:ir-claim-auditor`:
  `INPUT: report.md + evidence/ + corpus.json → claim-audit.md/.json;
   When finished: shards/audit.done`
- `intensive-research:ir-statistician`:
  `INPUT: report.md + evidence/ → stats-review.md (blocking: inconsistent=0);
   When finished: shards/stats.done`

**Gate G2 pass bar**: zero `MAJOR_DISTORTION`, zero `UNVERIFIABLE`, zero
`inconsistent` numericals. Failures route back: writer fixes the sentence or
drops the claim; re-audit only the changed claims. Max fix rounds per the
tier's revision-loop cap.

## 3. Gate G3 — deterministic final gate (you run this)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" audit-report \
  research/<slug>/report.md --corpus research/<slug>/corpus.json \
  --out research/<slug>/gate-report.json
```

Exit 0 = pass. Exit 1 → read `gate-report.json`, fix (uncited → cite from
corpus or delete; unverified → re-verify or delete; retracted → remove or
re-frame as retraction example), re-run. The gate is the exit code — never
assert G3 passed without a 0.

## 4. Finalize

- Append to `report.md`: **Run Receipt** (budget block from `passport.yaml` —
  agents spawned, API request counts from the ledger's `request_counts`
  entries, cache hits, wall time), **AI-disclosure** (prisma-protocol.md
  §AI-disclosure), and the **coverage manifest**.
- Complete `prisma.md` (flow counts + saturation curve).
- Offer exports: `scholar.py export --in corpus.json --format bibtex|ris|csl-json`.
- Update `passport.yaml` gates + `state.yaml` → `phase: done`.
- Tell the user: report path, gate results, included-paper count, and how to
  resume or extend (`/ir-status <slug>`, `/ir-watch <slug>`).
