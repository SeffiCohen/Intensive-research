---
description: Verify citations in a document/bibliography, or fact-check a claim, against scholarly indexes + the Retraction Watch database
argument-hint: "<file-or-claim>"
disable-model-invocation: true
---

Inspect the argument: $ARGUMENTS

- If it is a file (bibliography, paper, reference list): run the
  `citation-audit` skill on it
  (`${CLAUDE_PLUGIN_ROOT}/skills/citation-audit/SKILL.md`) — 100% verification
  + retraction screening + per-reference fixes.
- If it is a claim or question: run the `intensive-research` skill in
  `fact-check` mode — decompose the claim, retrieve evidence via scholar.py,
  and render supported / contradicted / unsettled verdicts with verified
  citations.
