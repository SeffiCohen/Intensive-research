# Source quality hierarchy

Condensed evidence-grading framework (derived from ARS `source_quality_hierarchy.md`;
see NOTICE.md). Screener and reviewers weight evidence by level; the synthesizer
resolves contradictions by weight, not by vote count.

## Evidence pyramid (strongest → weakest)

1. **Systematic reviews / meta-analyses** — pre-registered protocol (PROSPERO),
   comprehensive multi-database search, explicit criteria, quality assessment,
   PRISMA reporting. Caveat: only as good as the included studies; can date fast.
2. **Randomized controlled trials** — random allocation, control group,
   blinding, pre-registration, ITT analysis. Caveat: feasibility/ethics limits;
   external-validity concerns.
3. **Controlled studies without randomization** — quasi-experimental (DiD,
   propensity matching, regression discontinuity). Caveat: selection bias.
4. **Cohort / case-control studies** — observational with comparison groups.
   Caveat: confounding.
5. **Systematic reviews of descriptive/qualitative studies.**
6. **Single descriptive / qualitative studies / case reports.**
7. **Expert opinion / committee reports / editorials.**

For CS/ML (where the pyramid fits poorly), weight by: reproducibility (code +
data + seeds), benchmark rigor (held-out, no leakage, baselines), peer-review
status (published > peer-reviewed workshop > preprint), and independent
replication.

## Cross-cutting quality signals

- **Venue**: indexed, peer-reviewed, in DOAJ (for OA) > reputable preprint >
  unknown venue. Flag OA journals absent from DOAJ with other red flags as
  `VENUE_QUALITY` (possible predatory).
- **Independence**: multiple independent groups > single group > single lab.
  Watch author-set overlap and citation cartels.
- **Recency vs. contamination**: prefer current evidence, but flag post-2024
  preprints as a possible training-data contamination heuristic.
- **Retraction status**: a retracted source is excluded (via the retraction
  gate) unless cited *as* a retraction example.
- **Directness**: primary source > secondary description > tertiary summary.
  Cite the primary source for a claim, never a review's paraphrase of it.

## Predatory / low-quality red flags

Not in DOAJ (for an OA journal); implausibly fast "peer review"; fake or
non-existent impact metrics; editorial board that cannot be verified; spammy
solicitation; fee opacity. Two or more → `VENUE_QUALITY` exclusion (reversible
by the user).
