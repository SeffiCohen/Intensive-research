# Panel protocol

Decision standards derived from ARS `editorial_decision_standards.md` +
`sprint_contract_protocol.md` (see NOTICE.md), reduced to what earns its tokens.

## Panel composition (by intensity)

| Tier | Seats (all differentiated — never clones) |
|---|---|
| standard | methodology, domain, impact |
| intensive | + statistician, devil's-advocate |
| exhaustive | + second domain seat (different sub-field persona), claim-auditor |

Spawn the ENTIRE panel in one message (parallel Task calls). Each seat writes
`reviews/<seat>.md` and must NOT read the other reviews (independence is the
point of a panel).

## Sprint-contract-lite

Each reviewer states, before reading the manuscript, the criteria and evidence
thresholds they will score against (a short pre-commitment block at the top of
their review). This prevents retrofitting the rubric to the text. The
synthesizing step checks the review actually scored against its own contract.

## Synthesis → decision (the orchestrator does this)

1. Read all `reviews/*.md`. Tabulate dimension scores and P0/P1/P2 concerns.
2. **Disagreements are data**: where seats diverge by >20 points on a dimension
   or conflict on a P0, record a structured disagreement (seat A position,
   seat B position, adjudication, residual) — adjudicate on the evidence,
   never average it away silently.
3. Compute the weighted aggregate → decision per the rubric mapping.
4. Emit `reviews/meta-review.md`: decision, score table, adjudicated
   disagreements, and a deduplicated, prioritized revision list (P0 → P2), each
   item actionable and located.

## Revision loops

Per the intensity table: loops run only while aggregate < 80 or a P0 is open;
early-stop on <3-point movement with no P0. Re-review after a revision is a
NARROW pass: only the previously-open items plus a regression scan — reviewers
state up front which findings the loop addresses (the loop's sprint contract).

## Rebuttal-check mode

Given an author rebuttal + reviews: verify each reviewer point is addressed,
categorize (resolved / contested-with-evidence / unaddressed), and flag
rebuttal claims that misrepresent what the revision actually changed.
