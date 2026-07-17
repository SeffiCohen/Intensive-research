---
description: Multi-agent literature research (modes research | lit-review | systematic-review | fact-check | brief) with an intensity dial
argument-hint: "<question> [--mode research|lit-review|systematic-review|fact-check|brief] [--intensity standard|intensive|exhaustive]"
disable-model-invocation: true
---

Run the `intensive-research` skill with: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/intensive-research/SKILL.md` exactly:
doctor preflight, scope + intensity confirmation, then the phase state machine
with parallel subagent fan-out. Default mode `research`, default intensity
`standard`. `brief` = fast single-pass, no fan-out.
