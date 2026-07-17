---
description: Peer-review a paper or draft with a parallel multi-agent panel (3-7 differentiated reviewer seats) and an editorial decision
argument-hint: "<file> [--intensity standard|intensive|exhaustive] [--mode panel|single|rebuttal-check]"
disable-model-invocation: true
---

Run the `peer-review` skill with: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/peer-review/SKILL.md`: spawn the whole
panel in one parallel batch with sprint contracts and independence, synthesize
with structured-disagreement adjudication, and render the decision + prioritized
revision list.
