---
description: Export a verified corpus as BibTeX, RIS, CSV, or CSL-JSON (Zotero-importable)
argument-hint: "<corpus.json-or-slug> [--format bibtex|ris|csv|csl-json]"
disable-model-invocation: true
---

Arguments: $ARGUMENTS

Resolve the corpus file (a path, or `research/<slug>/corpus.json` from a slug).
Default format `bibtex`; run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scholar.py" export --in <corpus.json> \
  --format <bibtex|ris|csv|csl-json> --out <corpus-basename>.<ext>
```

Tell the user the output path and that RIS/CSL-JSON import cleanly into
Zotero/Mendeley (no live sync — one-shot export).
