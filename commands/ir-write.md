---
description: Write a paper, section, abstract, or related-work from a verified research corpus (claim-audited before delivery)
argument-hint: "<paper|section|abstract|related-work> [--from research/<slug>] [--words N]"
disable-model-invocation: true
---

Run the `paper-writing` skill with: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/paper-writing/SKILL.md`: corpus check
(offer intensive-research if none), outline checkpoint with the user, parallel
section writers with the citation marker grammar, then the claim audit and the
deterministic `scholar.py audit-report` gate before delivery.
