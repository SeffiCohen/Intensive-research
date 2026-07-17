# Phase 3 — Verification (Gate G1b)

Goal: 100% of the INCLUDED corpus existence-verified and retraction-screened.
Runs after screening so no calls are spent on screened-out papers, while
coverage of the included set stays total.

## 1. Deterministic batch (you run this directly via Bash)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" verify-batch \
  --in research/<slug>/corpus.json --out research/<slug>/corpus.json
```

This stamps every record with `verification` (status, indexes_agreed,
independent_count) and a fresh `retraction` block (local Retraction Watch DB +
Crossref update-to). The first run auto-loads the Retraction Watch database
(~68k records) into the cache.

## 2. Chase the residue (ONE ir-citation-verifier)

If any record is `not_found`, `single_index`, `unresolvable`, or `degraded`,
spawn `intensive-research:ir-citation-verifier` with:

```
CORPUS: research/<slug>/corpus.json
OUTPUT: research/<slug>/citation-verification.json
PASSPORT: research/<slug>/passport.yaml (update verification_summary)
When finished, create research/<slug>/shards/verify.done
```

It re-checks failures via web + targeted lookups and renders the gate verdict.

## 3. Gate G1b decision

- Any `fabricated` (id-keyed not_found confirmed nowhere) → **fail**: remove the
  record AND every claim that depended on it, or stop and report to the user.
- Any `retracted`/`withdrawal` (not cited as a retraction example) → **fail**:
  exclude with PRISMA code `RETRACTED`, re-tally.
- `single_index` by ID in an authoritative index → acceptable (enters corpus).
- `unresolvable` title-only → route to the human-review queue in the report's
  limitations; do not silently keep or drop.
- `degraded` → retry once later in the run; record in `passport.degradations`.

Update `passport.yaml`: `verification_summary`, gate G1b, and `prisma.md`
eligibility counts. `state.yaml` → `phase: analysis`.
