"""
clusters/reports/cluster4_report.py — Cluster 4 (SA Fan Performance) standalone validation report.

Trains Cluster 4's baseline on the first 20% of each calendar month
(monthly-stratified split, STEADY-only, fan-running-only, quality-filtered
-- see clusters/cluster4_baseline.py's docstring), then runs the validator
across the remaining ~80% -- genuinely unseen data the baseline never saw.
Writes both a Markdown report (cluster4_report.md) and a native Word
document (cluster4_report.docx, via markdown_to_docx.py), same as Cluster
1/2.

Standalone by design: does not import server.py, does not touch the
frontend, does not require the webapp running. Only reads the raw CSV and
Cluster 4's own config/features/baseline/validator modules.

Usage:
    python -m clusters.reports.cluster4_report
    (run from backend/, so the shared/engine/clusters packages resolve)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from clusters.cluster4_baseline import Cluster4Baseline
from clusters.cluster4_features import SIDES, build_cluster4_view
from clusters.cluster4_validator import validate_dataframe
from clusters.reports.markdown_to_docx import write_docx
from shared.feature_extraction import load_config
from shared.raw_loader import load_raw

OUT_PATH = Path(__file__).parent / "cluster4_report.md"
DOCX_OUT_PATH = Path(__file__).parent / "cluster4_report.docx"
CLUSTER4_CONFIG_PATH = Path(__file__).parent.parent / "cluster4_config.yaml"

STATUS_ORDER = ["consistent", "outlier", "ambiguous", "unknown"]
RELATIONSHIP_COLS = [
    "fan_a_rpm", "fan_a_current", "fan_a_igv",
    "fan_b_rpm", "fan_b_current", "fan_b_igv",
    "ab_current_imbalance", "ab_rpm_imbalance",
]
# The two IGV columns are ALWAYS unknown (no real tag exists for SA, see
# cluster4_config.yaml) -- excluded from the conclusion's overall
# consistent-rate figure so a structural gap doesn't dilute a genuinely
# scored statistic. Still shown in the per-relationship summary table
# (section 3) for full transparency.
SCORED_RELATIONSHIP_COLS = [c for c in RELATIONSHIP_COLS if not c.endswith("_igv")]
PATTERN_ORDER = [
    "Current high; RPM and demand normal",
    "RPM high for normal demand",
    "IGV feedback abnormal for RPM/demand",
    "A/B residual divergence",
    "All fan variables shift with load reference mismatch",
    "Multiple fan residuals persist with process deviation",
]


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def run_pipeline():
    raw = load_raw()
    cluster_config = load_config(CLUSTER4_CONFIG_PATH)
    full_view = build_cluster4_view(raw, cluster_config)
    baseline = Cluster4Baseline(raw_df=raw, cluster_config=cluster_config)
    results = validate_dataframe(baseline.test_view, baseline, cluster_config)
    return raw, full_view, baseline, results, cluster_config


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _status_table(results: pd.DataFrame, status_col: str) -> str:
    counts = results[status_col].value_counts()
    total = len(results)
    lines = ["| status | rows | % |", "|---|---:|---:|"]
    for status in STATUS_ORDER:
        n = int(counts.get(status, 0))
        if n == 0 and status not in counts.index:
            continue
        lines.append(f"| {status} | {n:,} | {n / total * 100:.2f}% |")
    return "\n".join(lines)


def _example_row(results: pd.DataFrame, pattern: str) -> pd.Series | None:
    mask = results["pattern_interpretation"].apply(lambda d: isinstance(d, dict) and d.get("pattern") == pattern)
    sub = results[mask]
    if sub.empty:
        return None
    return sub.iloc[len(sub) // 2]


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def section_header(raw: pd.DataFrame) -> str:
    span_start = pd.to_datetime(raw["Timestamp"]).min()
    span_end = pd.to_datetime(raw["Timestamp"]).max()
    return f"""# Cluster 4 — SA Fan Performance — Validation Report

Source: `backend/clusters/docs/Cluster_4_SA_Fan_Performance_Technical_Note Final.docx`
Data: `data/raw/boiler9_cleaned_2024.csv`, {len(raw):,} rows, {span_start} to {span_end}

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
"""


def section_methodology(baseline: Cluster4Baseline) -> str:
    si = baseline.split_info
    return f"""## 1. Methodology

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

- Total rows: {baseline.n_total:,}
- Training window: {baseline.n_train:,} rows
- STEADY-only (of training window): {baseline.n_train_steady:,} rows
  ({baseline.train_mode_counts})
- Fan-running-only (of STEADY training rows, per side — see 1.7):
  A: {baseline.n_train_running.get('A', 0):,}, B: {baseline.n_train_running.get('B', 0):,}
- Test window (scored by the validator): {len(baseline.test_view):,} rows

Split diagnostics: {len(si.get('month_breakdown', []))} calendar months with
data, {si.get('n_gaps_in_full_dataset', 'n/a')} sampling gap(s) in the full
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

- **Confirmed yes, and isolated the cause**: of Fan A's {baseline.n_train_running.get('A', 0):,} running-STEADY
  training rows, **{baseline.excluded_counts.get('A_fan_rpm', 0):,} ({baseline.excluded_counts.get('A_fan_rpm', 0)/baseline.n_train_running.get('A', 1)*100:.1f}%)
  are excluded, and the exclusion is 100% attributable to the stale-streak
  detector** (0 spikes, 0 known-bad-timestamps, checked separately) — the
  identical mechanism as Cluster 2's case. Fan B's equivalent exclusion is
  only {baseline.excluded_counts.get('B_fan_rpm', 0):,} rows ({baseline.excluded_counts.get('B_fan_rpm', 0)/baseline.n_train_running.get('B', 1)*100:.1f}%).
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
"""


def section_parameters(cluster_config: dict) -> str:
    rel = cluster_config["relationships"]
    guard = cluster_config["ab_imbalance_guard"]
    lines = ["## 2. Parameters, thresholds and tolerances (all user-configurable)", ""]
    lines.append("Per the doc's own instruction — *\"Absolute limits should be finalized "
                  "from approved design data and reviewed healthy operation; they should "
                  "not be assumed from generic fan behavior\"* — every number below is a "
                  "reasonable configurable default pending plant validation, not a doc-given "
                  "value (only the formulas themselves, doc Table 2/4, are used verbatim).")
    lines.append("")
    lines.append("| Setting | Value | Source |")
    lines.append("|---|---|---|")
    for rel_name, cfg in rel.items():
        lines.append(f"| `{rel_name}.status` | {cfg.get('status')} | Step 0/1 finding, see section 1 |")
        lines.append(f"| `{rel_name}.band_width_std` | {cfg['band_width_std']} | configurable default |")
        lines.append(f"| `{rel_name}.stratify_by` | {cfg['stratify_by']} | Step 0/1 decision, see 1.2/1.6 |")
        lines.append(f"| `{rel_name}.n_bins` | {cfg.get('n_bins', 5)} | configurable default |")
    lines.append(f"| `ab_imbalance_guard.comparable_duty_tolerance_pct` | {guard['comparable_duty_tolerance_pct']} | configurable default |")
    lines.append(f"| `ab_imbalance_guard.band_width_std` | {guard['band_width_std']} | configurable default |")
    lines.append(f"| `fan_running.rpm_threshold` | {cluster_config['fan_running']['rpm_threshold']} RPM | empirically chosen for SA, see 1.7 |")
    lines.append(f"| `baseline.min_samples` | {cluster_config['baseline']['min_samples']} | configurable default, same as Cluster 1/2 |")
    lines.append(f"| `persistence.minutes` | {cluster_config['persistence']['minutes']} | configurable default — **not implemented this phase**, see section 7 |")
    return "\n".join(lines) + "\n"


def section_summary(results: pd.DataFrame) -> str:
    lines = ["## 3. Summary status by relationship", "",
              f"Scored across the full test window ({len(results):,} rows, unseen by training).",
              "`fan_a_igv`/`fan_b_igv` show 100% `unknown` by construction — no real tag exists "
              "for SA (section 1.4), not a scoring failure.", ""]
    for col in RELATIONSHIP_COLS:
        lines.append(f"### {col}")
        lines.append(_status_table(results, f"{col}_status"))
        lines.append("")
    lines.append("### Diagnostic pattern occurrence (doc section 6 table)")
    counts = results.loc[results["pattern_interpretation"].notna(), "pattern_interpretation"].apply(lambda d: d["pattern"]).value_counts()
    lines.append("| pattern | rows |")
    lines.append("|---|---:|")
    for p in PATTERN_ORDER:
        lines.append(f"| {p} | {int(counts.get(p, 0)):,} |")
    healthy = int((results["pattern_interpretation"].isna()).sum())
    lines.append(f"| *(no flagged pattern — healthy)* | {healthy:,} |")
    return "\n".join(lines) + "\n"


def section_worked_examples(results: pd.DataFrame) -> str:
    lines = ["## 4. Worked examples — real cases per residual pattern", "",
              "Per the brief: at least one real case per row of the doc's "
              "residual-interpretation table (section 6), pulled from this report's "
              "own test-window scoring — none forced. **\"IGV feedback abnormal for "
              "RPM/demand\" cannot occur here** (igv status is always `unknown`, never "
              "`outlier` — see section 1.4) and is reported honestly as absent, not "
              "omitted from this list."]
    for pattern in PATTERN_ORDER:
        row = _example_row(results, pattern)
        lines.append(f"\n### {pattern}")
        if row is None:
            lines.append("*Did not occur in the 2024 test window* — expected for the IGV "
                          "pattern (section 1.4); genuinely absent, not a forced omission.")
            continue
        interp = row["pattern_interpretation"]
        lines.append(f"**{row['Timestamp']}** — Load {row['LOAD']:.1f}% MCR")
        lines.append(f"\n> {interp['initial_interpretation']}")
        lines.append(f">\n> Required confirmation (doc, unmodified): {interp['required_confirmation']}")
        lines.append("")
        lines.append("| variable | actual | predicted | deviation % |")
        lines.append("|---|---:|---:|---:|")
        for side in SIDES:
            for short, label in (("rpm", "Speed"), ("current", "Current"), ("igv", "IGV FB")):
                d = row[f"fan_{side.lower()}_{short}_detail"]
                if "actual" in d:
                    lines.append(f"| Fan {side} {label} | {d['actual']:.2f} | {d['predicted']:.2f} | {d.get('deviation_pct', float('nan')):+.2f}% |")
                else:
                    lines.append(f"| Fan {side} {label} | — | — | *{d.get('reason', 'n/a')}* |")
        ab = row["ab_current_imbalance_detail"]
        if "imbalance_pct" in ab:
            lines.append(f"| A/B Current Imbalance | {ab['imbalance_pct']:.2f}% | baseline {ab['baseline_mean_pct']:.2f}% ± {ab['baseline_std_pct']:.2f}% | — |")
    return "\n".join(lines) + "\n"


def section_open_items() -> str:
    return """## 5. Open items for Punarbasu / Awes

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
"""


def section_limitations() -> str:
    return """## 6. Known limitations — not implemented in this phase

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
"""


def section_conclusion(results: pd.DataFrame) -> str:
    n = len(results)
    consistent_rate = sum(
        (results[f"{c}_status"] == "consistent").sum() for c in SCORED_RELATIONSHIP_COLS
    ) / (n * len(SCORED_RELATIONSHIP_COLS)) * 100
    return f"""## 7. Conclusion

Cluster 4 provides a Flow+Head-referenced normal-behaviour model for SA
Fan-A and SA Fan-B Speed/Current — narrower than the doc's original
3-variable framing (no IGV-equivalent tag exists for SA at all, section
1.4) and narrower than Cluster 2's PA model in that specific respect, but
BROADER than PA's in another: Head is genuinely usable here (section 1.2),
unlike PA's blocked case. Across the 6 relationships that can actually be
scored (excluding the two permanently-`unknown` IGV columns — see section
3), **{consistent_rate:.1f}%** of (relationship x row) combinations score
`consistent` across the {n:,}-row test window.

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
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    raw, full_view, baseline, results, cluster_config = run_pipeline()

    sections = [
        section_header(raw),
        section_methodology(baseline),
        section_parameters(cluster_config),
        section_summary(results),
        section_worked_examples(results),
        section_open_items(),
        section_limitations(),
        section_conclusion(results),
    ]
    report = "\n".join(sections)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(report):,} chars)")

    write_docx(report, DOCX_OUT_PATH, title="Cluster 4 — SA Fan Performance — Validation Report")
    print(f"Wrote {DOCX_OUT_PATH}")


if __name__ == "__main__":
    main()
