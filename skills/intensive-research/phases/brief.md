# Brief mode (no fan-out)

For small questions: a single-pass, tool-grounded answer with light
verification. No subagents, no passport, no phases.

1. Run 2–4 `scholar.py search` queries yourself (pick sources by the playbook
   routing table). Skim the top results' abstracts.
2. Answer the question from what you retrieved, citing 3–8 papers inline as
   `Author (Year) [doi:...]`.
3. Verify the papers you actually cited (they came from the APIs, so existence
   is grounded; still run `scholar.py verify --doi ...` on any you emphasize,
   which also retraction-screens them).
4. State scope honestly: this was a brief scan, not a review — offer
   `/ir-research "<question>" --intensity standard` for the full pipeline.

No claim in the answer may rest on a paper you did not retrieve this session.
