---
description: One-time setup — environment check, polite-pool email, optional API keys, and the permission allowlist for unattended runs
argument-hint: ""
disable-model-invocation: true
---

Walk the user through setup:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" doctor` and explain
   any failing check.
2. **IR_MAILTO** (recommended): a contact email for the API polite pools —
   lifts OpenAlex/Crossref rate tiers and is REQUIRED for Unpaywall full-text
   resolution. Suggest adding `export IR_MAILTO=<their email>` to their shell
   profile, or `"env": {"IR_MAILTO": "..."}` in `.claude/settings.json`.
3. **Optional keys**: `OPENALEX_API_KEY` (free at openalex.org/settings/api;
   recommended for sustained use under OpenAlex's 2026 credit model —
   keyless still works at low volume), `NCBI_API_KEY` (PubMed 3→10 rps; free
   at ncbi.nlm.nih.gov/account), `S2_API_KEY` (enables Semantic Scholar as a
   third verification vote; free request form at
   semanticscholar.org/product/api).
4. **Retraction database**: offer to run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" cache load-retractions`
   now (~68k records, one-time, refreshes weekly on use).
5. **Unattended runs**: show the permission allowlist entries that let the
   pipeline run without per-call prompts, and ONLY with explicit consent append
   them to `.claude/settings.local.json`:
   ```json
   {
     "permissions": {
       "allow": [
         "Bash(python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py\" *)",
         "Agent(intensive-research:*)"
       ]
     }
   }
   ```
   Explain what each grants (the bundled read-only research CLI; spawning this
   plugin's subagents). Do not write the file without a clear yes.
