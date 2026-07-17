# Gap taxonomy

Every mined gap gets exactly one `type`. The taxonomy consolidates the
meta-research literature on research-gap identification — Robinson, Saldanha
& McKoy (2011, J Clin Epidemiol; the AHRQ evidence-gap framework), Miles
(2017; seven-gap typology), and Müller-Bloch & Kranz (2015, ICIS; gap
identification in literature reviews) — collapsed to eight types that are
each **detectable from text or metadata** and each imply a different kind of
future work.

| `type` | The missing thing | Detection signals |
|---|---|---|
| `evidence` | Findings exist but are insufficient or too weak to conclude (small N, no RCT, no replication, low-quality designs) | "evidence is limited/insufficient", "small sample", "no randomized", hedged conclusions in reviews; metadata: few primary studies behind a much-cited claim |
| `method` | No adequate method, instrument, dataset, or benchmark exists for a question people want to answer | "no standardized benchmark/measure", "lacks a validated instrument", "methods are not directly comparable"; metadata: every paper rolls its own evaluation |
| `theory` | Phenomenon documented, mechanism or explanatory framework absent | "mechanism remains unclear", "atheoretical", "why … is unknown", "lacks a unifying framework" |
| `population` | Question answered for population/setting/context A, silent for B | "generalizability", "only studied in", "Western/WEIRD samples", "excluded patients with"; metadata: homogeneous study settings across the corpus |
| `bridge` | Two literatures that should intersect barely do (Swanson's undiscovered public knowledge: A→B known, B→C known, A→C untested) | Nominated structurally (co-occurrence probes) or from text: "to our knowledge, X has not been applied to Y"; metadata: high `bridge_opportunity` |
| `contradiction` | Credible studies disagree and no study reconciles them | "conflicting/mixed results", "in contrast to", reviews tabulating discordant findings; metadata: contradicting conclusions on the same question in the corpus |
| `reproducibility` | Published finding lacks independent confirmation, open data/code, or survives only in one lab | "has not been replicated", "single-center", "code/data not available"; retraction/correction activity in the neighborhood |
| `translation` | Knowledge exists; application, deployment, implementation, or practice change does not | "clinical translation", "real-world validation", "remains to be implemented", implementation-science vocabulary |

## Rules of use

- Choose the **most specific** type that fits; `bridge` beats `population`
  when the essence is an untested pairing.
- The type is not a score — a `translation` gap is not inherently worth less
  than a `theory` gap; the metrics and the panel decide value.
- A statement too vague to type ("more research is needed on X") is not a
  gap; miners must sharpen it into the missing thing or drop it.
- Types map to future-work shapes the report proposes: `evidence` → primary
  study or systematic review; `method` → benchmark/instrument paper;
  `bridge` → transfer study; `contradiction` → reconciliation study or
  meta-analysis; `reproducibility` → replication; `translation` →
  implementation study.
