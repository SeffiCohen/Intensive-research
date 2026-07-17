---
description: Produce publication-quality figures (overview + results + PRISMA) with a render, vision-critique, and fix loop
argument-hint: "<research/<slug>> [--journal nature|cell|acs|ieee|plos] [--intensity ...]"
disable-model-invocation: true
---

Run the figure phase over the given run: $ARGUMENTS

Follow `${CLAUDE_PLUGIN_ROOT}/skills/paper-writing/phases/2.5-figures.md`. First
`scholar.py doctor --check-figures`. Build anchored `figures/<id>.data.json`
(and `scholar.py emit-prisma` for systematic reviews), then spawn
`ir-figure-designer` → `ir-figure-critic` in parallel batches and loop
revise→re-render to the tier cap. Deliver vector masters + PNG proofs via
`SendUserFile`. Every plotted value must be anchored to a verified source; when
matplotlib is absent, figures ship as spec + runnable code + caption.
