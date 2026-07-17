# Phase 0 — Venue calibration (before drafting)

Runs when `--venue "<name>"` is given. Learns the venue's house style as
statistics; exemplar prose never reaches the writer.

1. Spawn `intensive-research:ir-style-analyst` (a single agent — if you word it
   as a spawn, use "in ONE message"):
   ```
   VENUE: "<name>" [ISSN: <issn>]
   WORKSPACE: <workspace>/
   N: <tier: 3/5/8>
   OUTPUT: <workspace>/style_profile.json
   When finished: <workspace>/style_profile.done
   ```
2. Gate on `style_profile.done`. Read `style_profile.json` (NOT the exemplar
   text). Confirm `provenance.leak_check == "clean"`; if it warns, do not use
   the profile.
3. Add ONE line to the Step-2 writer prompt: "Condition on
   `<workspace>/style_profile.json` structural features only (see
   `${CLAUDE_PLUGIN_ROOT}/skills/paper-writing/references/venue-style.md`);
   honor its confidence level."
4. Record the venue-style ledger (exemplar DOIs + licenses + a
   non-copyrightable-features note) into the Material Passport.

If no venue is given, skip this phase entirely.
