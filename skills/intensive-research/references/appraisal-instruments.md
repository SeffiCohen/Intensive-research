# Critical-appraisal instruments

Select by study type. Used by the methodology reviewer and statistician for
risk-of-bias and evidence-certainty assessment. Report a traffic-light summary
(low / some concerns / high risk) per domain.

## RoB 2 — randomized trials

Five bias domains: (1) randomization process; (2) deviations from intended
interventions; (3) missing outcome data; (4) measurement of the outcome;
(5) selection of the reported result. Each low / some-concerns / high → overall
judgment.

## Newcastle-Ottawa Scale — observational (cohort / case-control)

Three groups, star-rated: (1) **Selection** of groups; (2) **Comparability** of
groups (controls for confounders); (3) **Outcome/Exposure** ascertainment.
Up to 9 stars; higher = lower risk.

## GRADE — certainty of a body of evidence (per outcome)

Start from design (RCT = high, observational = low), then rate down for: risk of
bias, inconsistency, indirectness, imprecision, publication bias; rate up
(observational only) for: large effect, dose-response, plausible confounding
that would reduce the effect. Result: high / moderate / low / very low certainty.

## AMSTAR 2 — systematic reviews

16 items; the 7 critical domains: protocol registered before start;
adequacy of the literature search; justification for excluding individual
studies; risk-of-bias assessment of included studies; appropriateness of
meta-analytic methods; consideration of risk of bias when interpreting results;
assessment of publication bias. Overall confidence: high / moderate / low /
critically low.

## CS / ML rigor checklist (no standard instrument fits)

- Held-out evaluation with no train/test leakage; contamination checked for
  post-cutoff data.
- Baselines are strong and fairly tuned; ablations isolate the contribution.
- Multiple seeds / runs with variance reported, not a single lucky run.
- Code, data, and configs released; results reproducible from them.
- Claims scoped to the benchmarks actually tested; no benchmark-to-capability
  overreach.
