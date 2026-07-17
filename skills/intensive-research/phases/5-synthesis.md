# Phase 5 — Synthesis + adversarial challenge (parallel)

Goal: an integrated evidentiary picture AND its strongest refutation, produced
simultaneously and reconciled.

## 1. Spawn BOTH in one message (parallel Task calls)

- `intensive-research:ir-synthesizer`:
  ```
  INPUT: research/<slug>/evidence/*.md + corpus.json
  OUTPUT: research/<slug>/synthesis.md
  When finished: research/<slug>/shards/synth.done
  ```
- `intensive-research:ir-devils-advocate`:
  ```
  INPUT: research/<slug>/evidence/*.md + corpus.json + passport question
  REFUTATIONS PER CLAIM: <1|2|3 per tier>
  OUTPUT: research/<slug>/challenge.md
  When finished: research/<slug>/shards/challenge.done
  ```

The advocate attacks the evidence base while synthesis integrates it — neither
waits for the other.

## 2. Adjudicate the challenge

When both `.done` markers exist, read `challenge.md`. For every `fatal` or
`serious` refutation, YOU adjudicate against `synthesis.md` and the evidence
notes:

- Refutation stands → the synthesis conclusion must change or carry the
  disagreement explicitly. Record a structured disagreement entry (claim,
  refutation, adjudication, residual uncertainty) — surfaced to the user in the
  report, never averaged away.
- Refutation fails → record why (one line).

If a refutation exposes a coverage hole (missing literature), run a targeted
wave-2 search for just that hole before adjudicating (≤2 searcher spawns,
within the tier's cap).

`state.yaml` → `phase: compile`.
