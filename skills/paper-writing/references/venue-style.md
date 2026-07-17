# Venue style-learning (learn structure, never copy content)

Before drafting, calibrate to the target venue's house style — as **statistics
about structure**, never its prose.

## Recipe

1. `scholar.py venue-sample --venue "<name>" [--issn <issn>] --n <3/5/8>
   --save exemplars/ --out exemplar-manifest.json` — resolve the venue
   (OpenAlex source → Crossref ISSN → DBLP) and fetch recent version-of-record
   exemplars; abstracts backfill from Crossref when OpenAlex stripped them.
2. `scholar.py style-profile --manifest exemplar-manifest.json
   --out style_profile.json` — deterministic, offline computation of the
   STYLE-PROFILE (section structure, length envelope, citation density,
   reference style, sentence stats, hedging rates, shared generic terminology).
3. The `ir-style-analyst` runs both commands and validates the profile — it
   never reads exemplar prose into context.

## The plagiarism firewall (defense in depth)

1. Exemplar full text reaches **neither** the writer **nor** the orchestrator —
   only `style_profile.json` (numbers + closed-vocab markers + short generic
   terms) crosses. The analyst asserts `provenance.leak_check == "clean"`.
2. After drafting, a hard verbatim screen:
   `scholar.py originality --draft report.md --against exemplar-manifest.json`
   flags any contiguous unquoted span longer than the threshold that appears in
   an exemplar or a verified cited source. **Any hit blocks G3/G4** — quote it
   properly or rewrite it.
3. `originality` is an **OA-corpus verbatim screen, not plagiarism clearance**;
   it reports coverage (`n_sources_with_text / n_total`) in the Run Receipt. A
   clean exit is not a guarantee of originality against paywalled text.

## What the writer conditions on

- **Structural / formatting only**: section sequence, per-section length
  envelope, reference style, citation density, figure panel-label case.
- **Descriptive, never targets**: sentence-length and hedging/booster rates —
  the writer does NOT tune prose to hit these (cargo-culting surface style over
  clarity, and unreliable at n=3–8).
- Honor `sample.confidence`: `low` (few OA full-text exemplars — common for
  closed venues) → treat the profile as a light hint.

The Material Passport records each exemplar DOI + license + fulltext source and
a note that only non-copyrightable style features were derived.
