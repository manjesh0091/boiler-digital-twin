# Cluster 4 — SA Fan Performance — Validation Report

Source: `backend/clusters/docs/Cluster_4_SA_Fan_Performance_Technical_Note Final.docx`
Data: `data/raw/boiler9_cleaned_2024.csv`, 91,767 rows, 2024-01-18 00:00:00 to 2024-12-31 23:55:00

Standalone offline pipeline, same phased methodology as Cluster 1/2 — read
the doc, verify real tag availability (Step 0), build config -> baseline ->
validator (Steps 1-3), produce this report (Step 4). **Not wired into any
live module or dashboard** — by design, same scope limitation as Cluster
1/2.

Structurally the SA mirror of Cluster 2 (PA Fan Performance) — same code
pattern reused directly — but NONE of Cluster 2's specific empirical
findings were assumed to carry over. Every one was independently re-checked
against SA's own real data; several came out differently (see section 1).

**Read this before the numbers below**: unlike PA, SA Fan Head is genuinely
usable (kept in the model, `stratify_by: [FLOW, HEAD]`) — but SA has no
control-position/IGV-equivalent tag at all (confirmed absent, not
differently-named). The `fan_igv` relationship is therefore never computed
for either fan (always `unknown`) — this model answers *"is each fan's
Speed/Current internally consistent with its own measured Flow and Head?"*,
with no IGV-based diagnostic at all, a narrower set of relationships than
either the doc's original 3-variable framing or Cluster 2's PA model.

## 1. Methodology

### 1.1 Doc artifacts (not technical findings)

The source `.docx` is a copy of Cluster 2's PA note with an incomplete
find/replace: the title still says "Cluster 2 - SA Fan Performance" (wrong
cluster number), and three places still say "PA"/"PA-system" where SA was
clearly intended (Table 5's "Model boundary", Table 6's cross-cluster row,
Table 7's RPM-high interpretation). Table 1 (the actual variable/tag table)
*was* correctly updated to SA throughout. Treated as SA everywhere here per
the doc's own stated intent (paragraph 3: "Cluster 4 groups each Secondary
Air (SA) fan's...") — not a decision, just noting the artifact.

### 1.2 SA Fan Head — usable, unlike PA (Step 0 finding)

`SA PR TO APH(A)` and `SA PR TO APH(B)` are confirmed genuinely distinct —
`pandas.Series.equals()` returns **False** (NOT a duplicate like PA's single
"PA PR TO HGG"/"PA PR TO APH (A)" pair). Real per-fan data. Caveat: the two
are extremely highly correlated with each other (`corr` = 0.99996, means
only ~1% apart: 550.6 vs 555.8) — real, but may not differentiate Fan A's
vs Fan B's model much in practice. Kept **in** the model — no Head-drop
decision needed here, unlike PA — `stratify_by: [FLOW, HEAD]` for all three
relationships (2-dimensional quantile bins; `cluster4_baseline.py` reuses
Cluster 2's binning code unchanged, since it was already written generically
over however many `stratify_by` columns a relationship declares).

### 1.3 SA Fan Flow — available, simpler than PA, but with real nulls

`SA FLOW- A` / `SA FLOW-B ` are already single per-fan tags — no two-header
average needed (unlike PA's `PA FLOW TO HGG -A (1)/(2)` pattern). Real
data-quality gap PA's flow tags didn't have: **14,782 nulls (16.1%) for A,
13,683 (14.9%) for B**. This flows through to the validator/baseline as
ordinary missing-data handling, but is the main driver of this cluster's
higher `unknown`/`ambiguous` rates versus Cluster 2's (see section 3) — not
a new bug, a direct consequence of this tag's own null rate.

### 1.4 SA control position (IGV-equivalent) — confirmed absent

Searched IGV/damper/vane/guide/position/control/FB/feedback keywords across
all 103 raw historian columns — zero SA-fan-specific hits. The only
FB-suffixed tags are PA's own `IGV FB` pair and unrelated `CV-116/121/104
FB` control-valve tags (already investigated and rejected as an unclear
spray-water-flow proxy elsewhere in this project). **Decision** (user,
2026-08-11): kept as a documented placeholder relationship
(`fan_igv.status: synthetic_needed` in `cluster4_config.yaml`) rather than
omitted from the config entirely, so the gap stays visible/auditable —
`cluster4_baseline.py`/`cluster4_validator.py` both check each
relationship's `status` and skip computation entirely for anything not
`available` — no crash, no fabricated values. Consequently "IGV feedback
abnormal for RPM/demand" (doc's residual-pattern table) can never fire here
— see section 4.

### 1.5 Training / test split and filters

Same monthly-stratified 20/80 chronological split as Cluster 1/2
(`shared/chronological_split.py`).

- Total rows: 91,767
- Training window: 18,340 rows
- STEADY-only (of training window): 18,279 rows
  ({'STEADY': 18279, 'LOW_LOAD': 61})
- Fan-running-only (of STEADY training rows, per side — see 1.7):
  A: 18,279, B: 18,279
- Test window (scored by the validator): 73,427 rows

Split diagnostics: 11 calendar months with
data, 10 sampling gap(s) in the full
dataset.

### 1.6 Flow-binned baseline, not Load-binned — checked fresh for SA, a materially different story than PA

`corr(Load, SA Fan-A Flow)` = **0.426**, `corr(Load, SA Fan-B Flow)` =
**0.422** — much stronger than PA's 0.11-0.14, so this was NOT dismissed on
the correlation number alone the way PA's was.

**Decomposed by time scale**, because a real global correlation can still
hide very different local behavior:

- Correlation of **monthly mean** Load vs monthly mean Flow = **0.815** — a
  real, fairly strong seasonal/slow co-drift exists (e.g. January averages
  both lower load (95.4%) and lower flow (50.6 tph); March averages both
  higher load (103.3%) and higher flow (61.5 tph)).
- Correlation **after removing each month's own mean** (within-month only)
  drops to **0.363** (r² ≈ 13%) — a real but moderate within-month
  relationship, not zero.
- The range-restriction test **pooled across the whole year** (all months'
  rows binned together by raw Load %) comes back essentially flat: ratio
  1.03 (within-bin std 103% of unconditional std). Pooling months this way
  is confounded, though — it doesn't mean no local relationship exists, only
  that this particular (month-blind) binning doesn't capture one.
- **Verified directly, not inferred**: per-month correlation varies hugely
  — December ≈ -0.03, November ≈ 0.08, March = 0.17, but April = **0.60**,
  May = 0.44, September = 0.44. The pooled 0.363 figure is an average
  across months with genuinely different coupling strength, not a
  uniform within-month relationship.
- Re-running the SAME range-restriction test **within a single month**
  confirms this directly: within March (a weak month), 1-point Load bins
  give ratio **1.15** (no shrinkage, consistent with its weak 0.17
  correlation). Within April (a strong month, r²=36%), the same bins give
  ratio **0.875** — real shrinkage, close to the theoretical value for a
  linear relationship of that strength (√(1-r²) = 0.80). So a within-month,
  narrow-Load-bin relationship genuinely DOES exist when a month has one —
  the flat pooled-across-months ratio reflects the pooling, not an absence
  of any real local relationship.

**Same decision as PA (bin by Flow, not Load) reached here too, but for a
materially different, now-verified reason**: not "no relationship exists"
(PA's finding, and not fully accurate for SA either) but "the coupling
strength itself varies month to month, and this baseline's Flow-only,
month-blind binning doesn't (yet) capture the within-month structure that's
been shown to exist." A joint month+Flow (or month+Load) baseline dimension
is a promising, now better-evidenced future improvement, not attempted this
phase — same spirit as section 1.4's IGV gap and Cluster 2's own noted
Fan-B-IGV limitation.

### 1.7 Fan-running derivation and fan-configuration mix — checked fresh for SA

No dedicated fan run/stop/trip tag exists for either fan (confirmed, same
as PA). Derived from Speed (doc's own suggestion) — **not** PA's 500 RPM
value copied over: SA Speed's 0.1th percentile sits at ~900-902, with
counts below 500 and below 700 identical (37/37 rows), confirming a clean,
wide gap independently of PA's. `fan_running.rpm_threshold: 600` sits in
that gap.

Fan-configuration mix: this plant runs BOTH SA fans essentially
continuously through 2024, same conclusion as PA reached independently.
**Two** real exceptions found — not the same event as PA's:

1. **2024-05-17, ~08:35-11:30** (~3 hrs) — Fan A drops to near-zero
   speed/current while Fan B stays steady (~207-211 A) — a genuine,
   coherent single-fan-stop event, SA-specific, a different date than PA's
   2024-03-21 event.
2. **2024-02-11 13:30** — same timestamp as PA's and Cluster 1's
   already-known historian sampling-gap event (`KNOWN_BAD_TIMESTAMPS`) — a
   plant-wide logging hiccup, not an SA-specific finding.

No per-configuration baselines built, same reasoning as Cluster 2.

### 1.8 A/B imbalance baseline — checked fresh, same fix as PA needed, different magnitude

SA's own check (not assumed from PA's ~47% Current offset): **Current
imbalance mean +13.7%** (IQR +11.9% to +16.2%, std 6.1 pts, full dataset) —
smaller in magnitude than PA's, but still clearly non-zero; a fixed
threshold at zero would still bias-flag most healthy rows. **Speed
imbalance**, like PA's RPM imbalance, genuinely IS centered near zero (mean
+0.03%, tight IQR). Both metrics get the SAME learned-STEADY-state-band
treatment as Cluster 2 for architectural consistency (not special-casing
Speed just because its offset happens to already be small).

### 1.9 Fan A Speed — same stale-exclusion mechanism as Cluster 2's IGV finding, checked explicitly, smaller and differently-shaped effect

Fan A's Speed tag repeats its exact previous reading in **61.6%** of rows,
versus **3.2%** for Fan B. Checked explicitly whether this trips the same
`shared/data_quality.py` stale-streak exclusion that thinned Cluster 2's
Fan B IGV training data, rather than assuming it does or doesn't:

- **Confirmed yes, and isolated the cause**: of Fan A's 18,279 running-STEADY
  training rows, **7,988 (43.7%)
  are excluded, and the exclusion is 100% attributable to the stale-streak
  detector** (0 spikes, 0 known-bad-timestamps, checked separately) — the
  identical mechanism as Cluster 2's case. Fan B's equivalent exclusion is
  only 146 rows (0.8%).
- **Checked whether this produces the same generalization failure**: Fan
  A's test-window RPM outlier rate (13.6% overall) is meaningfully higher
  than Fan B's (7.9%), worst in July (40.2% vs 14.2%) — a real,
  month-varying degradation in the same direction as Cluster 2's finding,
  not just a training-side statistic with no downstream effect.
- **But the underlying character is different, checked via the actual
  repeat-run-length distribution** (not assumed identical to Cluster 2's
  case): median run length is 1 (no repeat at all), only 2.75% of runs
  reach the 12-row exclusion threshold, and the longest runs reach up to
  697 rows (~58 hours). This is a heterogeneous mix of brief repeats plus
  occasional long holds — **not** Cluster 2's clean "constant for entire
  calendar months" pattern (which showed literal std=0 for full months at a
  time). Consistent with a coarser logging resolution or intermittent
  hold behavior on this specific tag, not a sensor fault, and a real but
  smaller-magnitude version of Cluster 2's finding (13.6% overall outlier
  rate here vs Cluster 2's 58.2% for Fan B IGV) — flagged with the same
  rigor, not assumed to be identical just because the mechanism matches
  (section 6).

## 2. Parameters, thresholds and tolerances (all user-configurable)

Per the doc's own instruction — *"Absolute limits should be finalized from approved design data and reviewed healthy operation; they should not be assumed from generic fan behavior"* — every number below is a reasonable configurable default pending plant validation, not a doc-given value (only the formulas themselves, doc Table 2/4, are used verbatim).

| Setting | Value | Source |
|---|---|---|
| `fan_rpm.status` | available | Step 0/1 finding, see section 1 |
| `fan_rpm.band_width_std` | 2.0 | configurable default |
| `fan_rpm.stratify_by` | ['FLOW', 'HEAD'] | Step 0/1 decision, see 1.2/1.6 |
| `fan_rpm.n_bins` | 5 | configurable default |
| `fan_igv.status` | synthetic_needed | Step 0/1 finding, see section 1 |
| `fan_igv.band_width_std` | 2.0 | configurable default |
| `fan_igv.stratify_by` | ['FLOW', 'HEAD'] | Step 0/1 decision, see 1.2/1.6 |
| `fan_igv.n_bins` | 5 | configurable default |
| `fan_current.status` | available | Step 0/1 finding, see section 1 |
| `fan_current.band_width_std` | 2.0 | configurable default |
| `fan_current.stratify_by` | ['FLOW', 'HEAD'] | Step 0/1 decision, see 1.2/1.6 |
| `fan_current.n_bins` | 5 | configurable default |
| `ab_imbalance_guard.comparable_duty_tolerance_pct` | 15.0 | configurable default |
| `ab_imbalance_guard.band_width_std` | 2.0 | configurable default |
| `fan_running.rpm_threshold` | 600.0 RPM | empirically chosen for SA, see 1.7 |
| `baseline.min_samples` | 20 | configurable default, same as Cluster 1/2 |
| `persistence.minutes` | 15 | configurable default — **not implemented this phase**, see section 7 |

## 3. Summary status by relationship

Scored across the full test window (73,427 rows, unseen by training).
`fan_a_igv`/`fan_b_igv` show 100% `unknown` by construction — no real tag exists for SA (section 1.4), not a scoring failure.

### fan_a_rpm
| status | rows | % |
|---|---:|---:|
| consistent | 51,799 | 70.54% |
| outlier | 10,005 | 13.63% |
| unknown | 11,623 | 15.83% |

### fan_a_current
| status | rows | % |
|---|---:|---:|
| consistent | 54,326 | 73.99% |
| outlier | 7,478 | 10.18% |
| unknown | 11,623 | 15.83% |

### fan_a_igv
| status | rows | % |
|---|---:|---:|
| unknown | 73,427 | 100.00% |

### fan_b_rpm
| status | rows | % |
|---|---:|---:|
| consistent | 56,582 | 77.06% |
| outlier | 5,793 | 7.89% |
| unknown | 11,052 | 15.05% |

### fan_b_current
| status | rows | % |
|---|---:|---:|
| consistent | 57,667 | 78.54% |
| outlier | 4,708 | 6.41% |
| unknown | 11,052 | 15.05% |

### fan_b_igv
| status | rows | % |
|---|---:|---:|
| unknown | 73,427 | 100.00% |

### ab_current_imbalance
| status | rows | % |
|---|---:|---:|
| consistent | 60,796 | 82.80% |
| outlier | 972 | 1.32% |
| ambiguous | 11,659 | 15.88% |

### ab_rpm_imbalance
| status | rows | % |
|---|---:|---:|
| consistent | 60,913 | 82.96% |
| outlier | 855 | 1.16% |
| ambiguous | 11,658 | 15.88% |
| unknown | 1 | 0.00% |

### Diagnostic pattern occurrence (doc section 6 table)
| pattern | rows |
|---|---:|
| Current high; RPM and demand normal | 2,581 |
| RPM high for normal demand | 6,292 |
| IGV feedback abnormal for RPM/demand | 0 |
| A/B residual divergence | 1,018 |
| All fan variables shift with load reference mismatch | 5,201 |
| Multiple fan residuals persist with process deviation | 1,217 |
| *(no flagged pattern — healthy)* | 57,118 |

## 4. Worked examples — real cases per residual pattern

Per the brief: at least one real case per row of the doc's residual-interpretation table (section 6), pulled from this report's own test-window scoring — none forced. **"IGV feedback abnormal for RPM/demand" cannot occur here** (igv status is always `unknown`, never `outlier` — see section 1.4) and is reported honestly as absent, not omitted from this list.

### Current high; RPM and demand normal
**2024-11-19 19:30:00** — Load 101.0% MCR

> Additional electrical/mechanical loading or current measurement issue.
>
> Required confirmation (doc, unmodified): Check persistence, A/B comparison, maintenance data and related pressures/flows.

| variable | actual | predicted | deviation % |
|---|---:|---:|---:|
| Fan A Speed | 1186.00 | 1168.92 | +1.46% |
| Fan A Current | 202.06 | 185.02 | +9.21% |
| Fan A IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| Fan B Speed | 1188.32 | 1191.73 | -0.29% |
| Fan B Current | 171.87 | 164.36 | +4.57% |
| Fan B IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| A/B Current Imbalance | 16.15% | baseline 13.06% ± 2.97% | — |

### RPM high for normal demand
**2024-05-09 00:35:00** — Load 102.7% MCR

> More speed is required than the learned baseline.
>
> Required confirmation (doc, unmodified): Check SA-system resistance, air delivery and fan control state.

| variable | actual | predicted | deviation % |
|---|---:|---:|---:|
| Fan A Speed | 1218.76 | 1297.80 | -6.09% |
| Fan A Current | 192.41 | 196.00 | -1.83% |
| Fan A IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| Fan B Speed | 1214.87 | 1242.91 | -2.26% |
| Fan B Current | 171.41 | 176.19 | -2.71% |
| Fan B IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| A/B Current Imbalance | 11.55% | baseline 13.06% ± 2.97% | — |

### IGV feedback abnormal for RPM/demand
*Did not occur in the 2024 test window* — expected for the IGV pattern (section 1.4); genuinely absent, not a forced omission.

### A/B residual divergence
**2024-04-22 00:10:00** — Load 100.2% MCR

> One fan behaves differently from its own baseline or companion fan.
>
> Required confirmation (doc, unmodified): Confirm equal duty and compare downstream A/B air conditions.

| variable | actual | predicted | deviation % |
|---|---:|---:|---:|
| Fan A Speed | 1189.00 | 1227.59 | -3.14% |
| Fan A Current | 180.54 | 196.00 | -7.89% |
| Fan A IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| Fan B Speed | 1199.51 | 1238.67 | -3.16% |
| Fan B Current | 168.39 | 176.49 | -4.59% |
| Fan B IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| A/B Current Imbalance | 6.96% | baseline 13.06% ± 2.97% | — |

### All fan variables shift with load reference mismatch
**2024-07-24 11:45:00** — Load 99.1% MCR

> Demand input may be unreliable, or operation is transient or Fan deterioration issue requiring investigation.
>
> Required confirmation (doc, unmodified): Validate load and steam-flow relationship before fan diagnosis.

| variable | actual | predicted | deviation % |
|---|---:|---:|---:|
| Fan A Speed | 1278.93 | 1286.81 | -0.61% |
| Fan A Current | 214.20 | 227.04 | -5.66% |
| Fan A IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| Fan B Speed | 1268.75 | 1290.14 | -1.66% |
| Fan B Current | 185.17 | 193.31 | -4.21% |
| Fan B IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| A/B Current Imbalance | 14.54% | baseline 13.06% ± 2.97% | — |

### Multiple fan residuals persist with process deviation
**2024-04-08 09:35:00** — Load 94.4% MCR

> Higher-confidence fan/system performance issue.
>
> Required confirmation (doc, unmodified): Escalate for cross-cluster and field verification.

| variable | actual | predicted | deviation % |
|---|---:|---:|---:|
| Fan A Speed | 1006.00 | 1097.43 | -8.33% |
| Fan A Current | 148.43 | 170.52 | -12.95% |
| Fan A IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| Fan B Speed | 1006.28 | 1103.90 | -8.84% |
| Fan B Current | 135.02 | 152.74 | -11.61% |
| Fan B IGV FB | — | — | *no real tag for this relationship -- see cluster4_config.yaml* |
| A/B Current Imbalance | 9.47% | baseline 13.06% ± 2.97% | — |

## 5. Open items for Punarbasu / Awes

Doc's own two queries (Table 1 area, same wording pattern as Cluster 2's
doc) — **already on the consolidated cross-module list**, not asked twice:

- Fuel-change / air-supply-vs-alert-reliability question (same as Cluster
  2/Module 2's coal-composition dependency question).
- Whether Fuel GCV should also be a reference variable (same as Cluster
  2's open item).

New items from this cluster's own build:

- **SA control-position/IGV-equivalent tag**: confirmed absent across the
  whole historian (section 1.4) — is there really no damper/vane feedback
  signal logged for these fans, or does one exist under a name this search
  didn't anticipate? If genuinely absent, the `fan_igv` relationship stays
  permanently unscoreable, not just blocked pending a lab report.
- **SA Fan Head correlation**: `SA PR TO APH(A)` and `(B)` correlate at
  0.99996 with each other (section 1.2) — is this expected (a shared
  header/plenum both taps draw from) or does it suggest one of the two
  taps isn't measuring what its name implies?
- **A/B Current structural offset**: why do SA Fan A and Fan B draw ~13.7%
  different current at comparable duty (section 1.8)? Smaller than PA's
  ~47% but same open question: different motor/fan rating, or different
  CT scaling?
- **Fan A Speed resolution**: confirmed real (61.6% repeat-previous-value
  rate vs Fan B's 3.2%, section 1.9) — is Fan A's Speed tag logged at a
  coarser resolution or on a longer hold/deadband than Fan B's, by design?

## 6. Known limitations — not implemented in this phase

- **No IGV-based diagnostic exists for SA at all** (section 1.4) — a
  structural gap, not an implementation gap; nothing to implement without a
  real tag.
- **Persistence / alarm timing not implemented.** Same scope limitation as
  Cluster 1/2's reports — each row scored independently, no rolling-
  persistence state machine.
- **Cross-cluster confirmation is out of scope.** Every `required_confirmation`
  string in this report is the doc's own text, unmodified; this validator
  does not attempt that confirmation itself. Same limitation as Cluster 2.
- **Fan A Speed's high training-exclusion rate (section 1.9) reflects a
  real, coarser logging resolution on that specific tag**, not confirmed
  fan-health information — flagged rather than silently absorbed into the
  baseline without comment.
- **The baseline is Flow-only and month-blind, but Load-Flow coupling
  strength varies seasonally — the current baseline likely under-uses
  available predictive signal in strong-coupling months.** Verified
  directly (section 1.6), not just inferred from the pooled correlation:
  per-month `corr(Load, Flow)` ranges from near-zero in weak months
  (December ≈ -0.03, March = 0.17) up to r² ≈ 36% in April (corr = 0.60),
  with May/September also fairly strong (~0.44 each). A within-month,
  narrow-Load-bin range-restriction test confirms this is a real,
  bin-level-usable relationship in strong months (April: within-bin std
  shrinks to 87.5% of unconditional, close to the theoretical 80% for that
  r²) and genuinely absent in weak ones (March: 115%, no shrinkage) — so
  this isn't just seasonal noise, it's a real signal the current model
  doesn't use. A future revision could add a monthly/seasonal
  stratification dimension to the baseline to capture this — the same
  general fix Cluster 1 already applied for its own SA/TA side-balance
  seasonal-drift finding (monthly-stratified training, see
  `clusters/cluster_baseline.py`'s docstring), adapted here to a
  month-aware *scoring* dimension rather than just a month-aware *training
  split*. Not implemented this phase — documented here so it isn't
  silently lost, same treatment as Fan B IGV's limitation in Cluster 2 and
  the persistence/alarm-timing gap above.
- **Quantile-based Flow/Head bins, band_width_std, comparable-duty
  tolerance, and the fan-running Speed threshold are all configurable
  defaults or empirically-chosen values, not doc-specified numbers** — see
  `clusters/cluster4_config.yaml` for every tunable field and its rationale.
- **Single fan-configuration baseline only** (both-running) — correct for
  this plant's actual 2024 operating history (section 1.7).
- **Not wired into `server.py` or the frontend** — by design, per this
  phase's scope, same as Cluster 1/2.

## 7. Conclusion

Cluster 4 provides a Flow+Head-referenced normal-behaviour model for SA
Fan-A and SA Fan-B Speed/Current — narrower than the doc's original
3-variable framing (no IGV-equivalent tag exists for SA at all, section
1.4) and narrower than Cluster 2's PA model in that specific respect, but
BROADER than PA's in another: Head is genuinely usable here (section 1.2),
unlike PA's blocked case. Across the 6 relationships that can actually be
scored (excluding the two permanently-`unknown` IGV columns — see section
3), **77.6%** of (relationship x row) combinations score
`consistent` across the 73,427-row test window.

Five of the doc's six residual-interpretation patterns genuinely occur in
this plant's real 2024 data; the sixth ("IGV feedback abnormal for
RPM/demand") cannot occur by construction and is reported as such, not
omitted (section 4).

**Not a copy of Cluster 2's conclusions**: this cluster's decisions were
each independently re-derived from SA's own data and came out genuinely
different from PA's in several places — Head is usable here (PA: blocked),
the Load-Flow relationship is real but seasonally-mediated here (PA:
essentially absent), the A/B Current offset is ~14% here (PA: ~47%), and
the fan-running/stop events are different dates entirely. The one
consistent finding across both clusters is architectural, not numerical:
applying either doc's formulas literally, without checking real data
first, would have produced a misleading model in at least one place — for
PA it was the Load-Flow assumption and the A/B imbalance zero-point; for
SA it's the same two categories of finding, but with different magnitudes
and a different root cause for the Load-Flow result. Root-cause assignment
for any flagged pattern still requires the data-quality, operating-state,
SA pressure/flow, and maintenance evidence the doc itself calls for — this
cluster flags deterioration or control inconsistency early; it does not
diagnose it alone.
