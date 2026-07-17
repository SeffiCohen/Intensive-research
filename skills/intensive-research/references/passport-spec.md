# Material Passport & gates (spec)

The passport is the provenance ledger and the resume boundary for a run. It is a
single YAML file at `research/<slug>/passport.yaml`. Simplified from ARS's
Schema 9 (see NOTICE.md) — provenance and gates survive; the schema bureaucracy
does not.

## `passport.yaml` schema

```yaml
spec_version: "1"
slug: <topic-slug>
question: <the research question>
mode: research | lit-review | systematic-review | fact-check | brief
intensity: standard | intensive | exhaustive
criteria:                      # inclusion/exclusion, used by the screener
  include: [ ... ]
  exclude: [ ... ]
created_at: <iso>

corpus_summary:
  candidates: <n>              # pre-screen, post-dedup clusters
  included: <n>
  excluded_by_reason: { OFF_TOPIC: n, RETRACTED: n, ... }
  unclear_no_abstract: <n>

verification_summary:          # written by the citation-verifier (G1b)
  total: <n>
  verified: <n>
  single_index: <n>
  unresolvable: <n>
  fabricated: [ids]            # MUST be empty to pass
  retracted: [ids]             # MUST be empty (unless cited as example)
  degraded: [ids]

gates:                         # each: pending | pass | fail (+ note)
  G1a_identification: pending  # every record has provenance/resolved lookup
  G1b_existence:      pending  # 100% of included verified, ≥ semantics met
  G2_claim_audit:     pending  # 0 MAJOR_DISTORTION, 0 UNVERIFIABLE
  G3_final:           pending  # scholar.py audit-report exit 0

budget:                        # the Run Receipt
  agents_spawned: <n>
  searcher_spawns: <n>
  api_requests: { openalex: n, crossref: n, ... }
  cache_hits: <n>
  wall_seconds: <n>

coverage_manifest:             # honest limitations — ALWAYS filled
  searched: [openalex, crossref, ...]
  not_searched:
    - "books / monographs (no full-text API)"
    - "theses & grey literature"
    - "patents; standards; clinical-trial registries"
    - "non-English databases (no ToS-clean API)"
    - "subscription indexes (Scopus, Web of Science)"
    - "Google Scholar (no API; ToS prohibits automation)"
  language_scope: <e.g. English-first>
  notes: <field-specific caveats>

degradations: []               # [{component, reason, ts}] every skipped/degraded check
```

## Gates

- **G1a — identification** (at discovery): every candidate record carries API
  provenance (a `provenance.source_apis` entry) OR, for a snowballed reference
  string, a resolved single-index lookup. Snowballed reference strings are the
  one true fabrication surface — resolve them at intake.
- **G1b — existence** (after screening, on included papers only): run
  `scholar.py verify-batch`. 100% of included papers must be `verified` or
  `single_index`; any `not_found`→fabricated or `retracted` (non-example) is a
  hard fail. Verification runs post-screen so it never spends calls on papers
  that get screened out (~60–80% saving) while staying 100% of the included set.
- **G2 — claim audit** (after drafting): the claim-auditor + statistician cover
  100% of claims. Pass bar: zero `MAJOR_DISTORTION`, zero `UNVERIFIABLE`.
- **G3 — final** (before finalize): `scholar.py audit-report report.md
  --corpus corpus.json` must exit 0 (no uncited / unverified / retracted
  citations; deterministic). This is a program exit code, not an agent claim.

A gate that cannot pass blocks the pipeline. Record the reason in `gates` and,
if a check degraded (API down), in `degradations` — never silently skip.

## Resume

`state.yaml` (separate, machine-written) records the current phase, gates
passed, and artifact paths. A fresh session resumes by reading `passport.yaml`
+ `state.yaml`; `/ir-status` reports the resume point. Writer/orchestrator
refuse to resume across an incompatible `spec_version`.
