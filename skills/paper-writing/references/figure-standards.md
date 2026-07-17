# Figure standards & integrity

Thin plugin layer over the environment's figure skills. The `ir-figure-designer`
renders; the `ir-figure-critic` reads the PNG and enforces this.

## Journal profile registry

```yaml
generic:
  col_width_mm: {single: 90, one_half: 140, double: 190}
  dpi_raster: 300
  dpi_lineart: 600
  color_mode: RGB
  font: [Arial, Helvetica]
  body_pt: 7
  panel_label_pt: 8
  panel_label_case: lower       # a, b, c
  vector_formats: [pdf, svg]
nature:
  col_width_mm: {single: 89, one_half: 120, double: 183}
  dpi_raster: 300
  panel_label_case: lower       # Nature uses lowercase a b c
  font: [Arial, Helvetica]
cell:
  panel_label_case: upper       # A B C
  font: [Arial]
ieee:
  panel_label_case: upper
  font: [Times New Roman, Arial]
acs:
  panel_label_case: upper
  dpi_raster: 300
plos:
  panel_label_case: upper
  dpi_raster: 300
```

## Report-type → standard figure

| Report type | Standard figure |
|---|---|
| Systematic review | PRISMA flow (`scholar.py emit-prisma` → DOT/SVG → render) |
| Meta-analysis | Forest plot (+ funnel when ≥10 studies) |
| RCT | CONSORT participant-flow diagram |
| Observational | STROBE flow |
| Any results | bar / line with error bars + n |
| Method | original overview/schematic |

## Figure-integrity ruleset (the critic + `meta.json` enforce)

- **Zero baseline** for count/ratio/percentage bars; a truncated axis on such a
  bar is a violation.
- **No broken or dual axis** unless explicitly labeled as an inset.
- No misleading aspect ratio or scale; log axes labeled as such.
- **Colorblind-safe**: Okabe-Ito palette, with redundant shape/pattern encoding
  (never rely on color alone; never jet/rainbow for sequential/diverging data).
- **Error bars** must declare their type (SD / SEM / 95% CI) and n.
- **Significance marks** (`*`, `**`) require the test, n, and effect in the
  figure or caption.
- **Originality**: schematics are original/conceptual — never trace, screenshot,
  or copy a source figure. CC-licensed icons need an attribution string.
- **Duplicate-panel detection**: `hashlib` exact-hash of emitted panel files is
  always run; Pillow perceptual near-dup only if Pillow is installed (else
  exact-only, reported as review-needed — not full integrity coverage).

## Runtime

Figures need the user's Python (`matplotlib`, `pillow`, `numpy`; system
`graphviz` for schematics). Run `scholar.py doctor --check-figures` first. When
the runtime is absent the deliverable is **spec + runnable `.py` + caption**
with `render_status: deferred`; a deferred figure embedded as a rendered result
(`![](figures/...)`) in the manuscript **fails G4**.
