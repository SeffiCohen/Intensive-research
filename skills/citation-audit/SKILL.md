---
name: citation-audit
description: Standalone citation integrity audit of any document or bibliography. Extracts references (markdown, BibTeX, numbered lists, or bare DOIs), verifies 100% of them across independent scholarly indexes, screens every DOI against the Retraction Watch database, and reports per-reference verdicts with suggested fixes. Use to check citations in any paper, thesis, blog post, or reference list. Do NOT use for full literature research (intensive-research).
argument-hint: "<file-with-citations-or-bibliography>"
---

# Citation Audit — standalone gate

You certify someone else's reference list. 100% coverage, deterministic
backbone, honest verdicts.

## Step 1 — Extract references

Read the file. Handle whichever forms appear:
- BibTeX entries → parse title/author/year/DOI per entry.
- Numbered or author-year reference lists → parse each line into
  `{title, authors, year, doi?, arxiv?}`.
- Inline DOIs/arXiv ids → collect directly.
- This plugin's own `[@id]{...}` markers → note that `scholar.py audit-report`
  is the better tool if a corpus.json exists, and use it.

Write the parsed list to `refs.jsonl` (one JSON object per line). Show the
user the count and ask about ambiguous parses rather than guessing.

## Step 2 — Deterministic verification (you run this)

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" verify-batch --in refs.jsonl --out refs-verified.json
```
First run auto-loads the Retraction Watch database (~68k records). Each entry
gets `verification` (status, indexes_agreed, independent_count) and
`retraction`.

## Step 3 — Chase the residue

If anything is `not_found` / `single_index` / `unresolvable` / `degraded`,
spawn ONE `intensive-research:ir-citation-verifier` with the file and let it
chase failures via web + targeted lookups (it distinguishes fabricated from
merely-unindexed).

## Step 4 — Report

A per-reference table: status, indexes agreed, retraction status, and a
suggested fix where applicable (corrected DOI, corrected year, published
version of a preprint via the bioRxiv/Europe PMC resolution, "possible
fabrication — no trace in any index"). Summarize: verified / single-index /
unresolvable / fabricated / retracted counts. Flag corrections/EoC as warnings.
Offer `scholar.py export` of the cleaned list.

Honesty rules: `degraded` (an index was down) is never reported as a failure;
title-only matches below the exact-normalized bar are `unresolvable`, not
"wrong"; generic titles without an id cannot be certified either way.
