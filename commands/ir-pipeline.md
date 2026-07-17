---
description: End-to-end pipeline — research → write → panel review → bounded revisions → final citation gate, refusing to advance past a failing gate
argument-hint: "<topic> [--intensity standard|intensive|exhaustive] [--target paper|report]"
disable-model-invocation: true
---

Run the `research-pipeline` skill with: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/research-pipeline/SKILL.md`: doctor
preflight, full-pipeline cost confirmation, then chain
intensive-research → paper-writing → peer-review → revision loops → the final
`scholar.py audit-report` gate. Never advance past a failing gate.
