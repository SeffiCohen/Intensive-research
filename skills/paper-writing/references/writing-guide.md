# Writing guide

Style and structure discipline for the writer (partially derived from ARS
writing references; see NOTICE.md).

## Structure

- **IMRaD** for empirical work (Intro → Methods → Results → Discussion);
  **thematic** for reviews (themes ordered by the synthesis's convergence
  matrix, not paper-by-paper annotation).
- Every section gets a word budget from the outline; track and report drift.
- Introductions end with explicit contributions/questions. Discussions own the
  limitations honestly — import the coverage manifest, don't soften it.

## Claims discipline

- Hedge strength must match evidence strength from the synthesis: `established`
  (multiple independent strong studies) → plain assertion; `suggested` (limited
  or single-group evidence) → "evidence suggests"; `contested` → present the
  disagreement with both sides cited.
- One claim per sentence where possible — it makes the claim audit tractable.
- Absolute dates, never deictic ("in 2024", not "recently"; "as of July 2026",
  not "currently"). The G3 lint flags violations.
- Numbers come from evidence notes verbatim; never round in a direction that
  strengthens the claim.

## Citation discipline

- Marker grammar (hard contract, checked by `scholar.py audit-report`):
  `[@corpus_id]{anchor=quote:"≤25 words"|page:N|section:S|none}`.
- Cite the primary source, not a review's paraphrase of it.
- Preprints render with a "(preprint — not peer reviewed)" tag.
- A `[RETRACTED]` tag is mandatory when a retracted work is discussed as such.

## Anti-tells (machine-prose hygiene)

Avoid: "delve", "tapestry", "it's important to note", "in conclusion" openers,
triple-adjective lists, uniformly medium-length sentences, hedging every
sentence identically, bullet lists where prose should argue. Vary rhythm; argue,
don't enumerate. No em-dash chains as a crutch.

## Bilingual / venue notes

Default English. If the user names a venue, mirror its section conventions and
citation style at export time (`scholar.py export` gives BibTeX/RIS/CSL-JSON for
the reference manager to format).
