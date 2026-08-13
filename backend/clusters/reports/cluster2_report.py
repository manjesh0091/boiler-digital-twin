"""
clusters/reports/cluster2_report.py — Cluster 2 (PA Fan Performance) standalone validation report.

Trains Cluster 2's baseline on the first 20% of each calendar month
(monthly-stratified split, STEADY-only, fan-running-only, quality-filtered
-- see clusters/cluster2_baseline.py's docstring), then runs the validator
across the remaining ~80% -- genuinely unseen data the baseline never saw.
Writes both a Markdown report (cluster2_report.md) and a native Word
document (cluster2_report.docx, via markdown_to_docx.py), same as Cluster 1.

Standalone by design: does not import server.py, does not touch the
frontend, does not require the webapp running. Only reads the raw CSV and
Cluster 2's own config/features/baseline/validator modules.

Usage:
    python -m clusters.reports.cluster2_report
    (run from backend/, so the shared/engine/clusters packages resolve)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from clusters.cluster2_baseline import Cluster2Baseline
from clusters.cluster2_features import SIDES, build_cluster2_view
from clusters.cluster2_validator import validate_dataframe
from clusters.reports.markdown_to_docx import write_docx
from shared.feature_extraction import load_config
from shared.raw_loader import load_raw

OUT_PATH = Path(__file__).parent / "cluster2_report.md"
DOCX_OUT_PATH = Path(__file__).parent / "cluster2_report.docx"
CLUSTER2_CONFIG_PATH = Path(__file__).parent.parent / "cluster2_config.yaml"

STATUS_ORDER = ["consistent", "outlier", "ambiguous", "unknown"]
RELATIONSHIP_COLS = [
    "fan_a_rpm", "fan_a_current", "fan_a_igv",
    "fan_b_rpm", "fan_b_current", "fan_b_igv",
    "ab_current_imbalance", "ab_rpm_imbalance",
]
PATTERN_ORDER = [
    "Current high; RPM and demand normal",
    "RPM high for normal demand",
    "IGV feedback abnormal for RPM/demand",
    "A/B residual divergence",
    "All fan variables shift with load reference mismatch",
    "Multiple fan residuals persist with process deviation",
]
PATTERN_DOC_ROW = {
    "Current high; RPM and demand normal": "Current high; RPM and demand normal",
    "RPM high for normal demand": "RPM high for normal demand",
    "IGV feedback abnormal for RPM/demand": "IGV feedback abnormal for RPM/demand",
    "A/B residual divergence": "A/B residual divergence",
    "All fan variables shift with load reference mismatch": "All fan variables shift with load reference mismatch",
    "Multiple fan residuals persist with process deviation": "Multiple fan residuals persist with process deviation",
}


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def run_pipeline():
    raw = load_raw()
    cluster_config = load_config(CLUSTER2_CONFIG_PATH)
    full_view = build_cluster2_view(raw, cluster_config)
    baseline = Cluster2Baseline(raw_df=raw, cluster_config=cluster_config)
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
    return f"""# Cluster 2 — PA Fan Performance — Validation Report

Source: `backend/clusters/docs/Cluster_2_PA_Fan_Performance_Technical_Note Final.docx`
Data: `data/raw/boiler9_cleaned_2024.csv`, {len(raw):,} rows, {span_start} to {span_end}

Standalone offline pipeline, same phased methodology as Cluster 1 (Load-Flow
Mass Balance) — read the doc, verify real tag availability (Step 0), build
config -> baseline -> validator (Steps 1-3), produce this report (Step 4).
**Not wired into any live module or dashboard** — by design, same scope
limitation as Cluster 1.

**Read this before the numbers below**: because PA Fan Head is unavailable
and Load doesn't explain Fan Flow in this plant's real data (section 1.3),
this model answers *"is each fan's RPM/Current/IGV internally consistent
with its own measured Flow?"* — not *"is the fan correctly responding to
boiler demand?"*, which is what Table 3's original demand-referenced
framing (`f(Fan Flow, Fan Head, Steam Flow)`) implied. That's still a valid
and useful diagnostic — a fan whose speed/current/IGV don't match its own
Flow is a real signal worth investigating — but it is a different question
than the doc originally posed, and a residual flagged here does not by
itself mean the fan is failing to keep up with demand.
"""


def section_methodology(baseline: Cluster2Baseline) -> str:
    si = baseline.split_info
    return f"""## 1. Methodology

### 1.1 Head decision (Step 0)

No "PA Fan A Head" / "PA Fan B Head" tag exists anywhere in the raw
historian. Exactly ONE PA-side pressure tag exists at all (`PA PR TO HGG`),
and it is a byte-identical duplicate of `PA PR TO APH (A)` (verified via
`pandas.Series.equals()` across all 91,767 rows) — the same physical tap
logged twice under two names, not two real readings. No `(B)` counterpart
exists (unlike SA, which genuinely has both `SA PR TO APH(A)` and
`SA PR TO APH(B)`).

**Decision** (user, 2026-08-11): Head is dropped from all three relationship
formulas (doc Table 3: `Fan RPM/IGV/Current = f(Fan Flow, Fan Head, Steam
Flow)`, reduced here to `f(Fan Flow)`). This is a config-driven decision —
`clusters/cluster2_config.yaml`'s `relationships.*.stratify_by` lists
currently read `[FLOW]` only; adding a real per-fan Head tag later (status:
`available`) and appending `HEAD` to a relationship's `stratify_by` list is
intended to be sufficient, with no baseline/validator code change, since
`cluster2_baseline.py`'s binning is written generically over however many
`stratify_by` columns are configured (see 1.3).

A candidate Head substitute was found and is extracted for reference only,
NOT used in any relationship: `PA PR AT AIR BOX A/B/C` — three real, clean,
independently-varying pressure tags downstream at the windbox. Not the same
physical point as fan discharge head, and the A/B/C-to-fan-A/B
correspondence is unconfirmed (a third "C" zone has no obvious fan mapping
at all) — flagged for Punarbasu, not silently adopted.

### 1.2 Training / test split and filters

Same monthly-stratified 20/80 chronological split as Cluster 1
(`shared/chronological_split.py`) — trains only on the first 20% of each
calendar month's own span, scores the remaining ~80% (genuinely unseen).

- Total rows: {baseline.n_total:,}
- Training window: {baseline.n_train:,} rows
- STEADY-only (of training window): {baseline.n_train_steady:,} rows
  ({baseline.train_mode_counts})
- Fan-running-only (of STEADY training rows, per side — see 1.4):
  A: {baseline.n_train_running.get('A', 0):,}, B: {baseline.n_train_running.get('B', 0):,}
- Test window (scored by the validator): {len(baseline.test_view):,} rows

Split diagnostics: {len(si.get('month_breakdown', []))} calendar months with
data, {si.get('n_gaps_in_full_dataset', 'n/a')} sampling gap(s) in the full
dataset (see `shared/chronological_split.py`).

### 1.3 Flow-binned baseline, not Load-binned — checked empirically, range-restriction ruled out

Module 1/Cluster 1 both bin by LOAD using fixed edges `[0,80,90,100,110,120]`
(% MCR). Cluster 2 does NOT reuse those edges — checked first, not assumed:

- `corr(Load, Fan-A Flow)` = 0.139, `corr(Load, Fan-B Flow)` = 0.106 —
  essentially no linear relationship in this real dataset.
- `corr(Fan-A Flow, Fan-B Flow)` = 0.994 — the two fans' own flows track
  each other almost perfectly.

**Range-restriction check.** A weak correlation between two variables that
both occupy a narrow range can be a statistical artifact, not a real
absence of relationship — Load itself is compressed to ~87-111% MCR nearly
all year (CV 3.88%), and Flow's own range is narrow too (CV 2.51-2.52%), so
this was checked directly rather than assumed away:

- If Load genuinely drove Flow, conditioning on a narrow Load slice should
  shrink Flow's spread well below its unconditional (whole-dataset) spread
  — that's what "Load explains Flow's variance" means. Computed directly:
  binning Load into 1-percentage-point-wide bins (e.g. exactly 100-101%
  MCR, n=10,735) and comparing each bin's Flow std against Flow's
  unconditional std.
- Result: the average within-Load-bin Flow std is **101.1% of Flow's
  unconditional std** (Fan A) and **100.2%** (Fan B) — i.e. knowing Load
  to within one percentage point explains approximately ZERO of Flow's
  variance, not just "not much." Within a single narrow load bin (n>10,000
  rows, load pinned at 100-101%), Fan A Flow still ranges 33.6-42.4 tph —
  nearly its entire full-dataset range (33.5-43.9 tph). In r² terms
  (variance explained under a linear model), Load explains ~1.95% of Fan A
  Flow's variance and ~1.13% of Fan B's.

This rules out range restriction as the explanation for the weak
correlation — if it were a range-restriction artifact, narrowing the Load
window further should have revealed Flow tightening up correspondingly,
and it does not. **Flow is genuinely driven by something independent of
demand in this plant's real 2024 operation** (most likely damper/IGV
position or fan-combination/control choices not captured by Load alone) —
a materially different physical story from the doc's own framing ("As
boiler demand rises, PA fan output generally has to increase"), not merely
a data-availability caveat.

Given the doc's own Table 3 formula treats Fan Flow (not Load) as the
primary input, and Load demonstrably doesn't explain Flow variance in this
plant's real 2024 data (confirmed above, not a range artifact), each
relationship's baseline is binned by the fan's OWN Flow instead. Flow has
no natural "% of something" scale the way Load does, so bin edges are
QUANTILE-based (5 bins by default, `n_bins` in cluster2_config.yaml),
computed from the STEADY+running training data itself, with the outer
edges widened to +/-inf so any scoring-time value always falls in some
bin.

### 1.4 Fan-running derivation and fan-configuration mix — checked empirically

No dedicated fan run/stop/trip tag exists for either fan (confirmed, Step
0). Derived from RPM per the doc's own suggestion ("Fan running condition
can be determined from Fan Speed") — both fans' RPM sit at 1085+ for 99.9%+
of the year, with a clean, wide gap down to two real exceptions —
`fan_running.rpm_threshold: 500` (RPM) in cluster2_config.yaml sits cleanly
in that gap.

Fan-configuration mix: this plant runs BOTH PA fans essentially
continuously through 2024 — 99.93%+ of rows have both fans above the
running threshold. **Two** exceptions exist, confirmed distinct in nature
(checked at raw-tag resolution, not assumed identical just because both
trip the same guard):

1. **2024-03-21, ~08:00-13:30** (widest window the guard trips across; the
   sharpest near-zero dip in current specifically is a narrower ~10:15-13:20
   sub-window) — Fan A's RPM/current/IGV all decay together while Fan B's
   RPM/current visibly *rise* to compensate. A physically coherent
   single-fan-stop signature — a genuine operational event (see section
   4's "Multiple fan residuals" worked example, drawn from this event).
2. **2024-02-11 13:25-13:30** (2 rows) — BOTH fans' RPM/current drop
   together, immediately followed by a 25-minute historian sampling gap
   (13:35-13:55), then both recover together at 14:00. This timestamp is
   already documented in `shared/data_quality.py`'s `KNOWN_BAD_TIMESTAMPS`
   as a Steam Flow-B glitch coinciding with a broader logging hiccup — this
   reads as the same brief data-quality/logging dropout affecting both fans
   at once, not a new finding about fan behavior or a second operational
   configuration change.

**No per-configuration baselines are built** (Fan-A-only / Fan-B-only /
changeover) — there is no meaningful training population for any
configuration other than "both running," checked empirically rather than
assumed, per the brief's explicit instruction.

### 1.5 A/B imbalance baseline — a real bug found and fixed during Step 3

Applying the doc's literal formula, `A/B Current Imbalance (%) =
(Current_A - Current_B) / avg * 100`, and flagging anything beyond a fixed
threshold around 0%, was tried first and produces a **false alarm on
essentially every row**: Fan A and Fan B draw structurally different
current at comparable duty/RPM in this plant (Fan A mean ~328 A, Fan B mean
~532 A — a stable ~-47.2% offset, IQR -47.5% to -46.8%, std only 0.62
percentage points during STEADY+comparable-duty operation). RPM imbalance,
by contrast, genuinely IS centered near zero (-0.41% mean).

This matches the doc's own Table 4 framing exactly: *"A small and stable
difference indicates normal unequal load sharing... A sudden increase or a
continuously rising difference may indicate a change"* — the doc anticipates
a non-zero, stable baseline, not that 0% is automatically "normal." Fixed by
giving both imbalance metrics their own LEARNED STEADY-state band (global,
not Flow-binned — the doc frames this as "stable," not load-dependent), and
scoring actual imbalance against that learned band instead of a fixed
threshold at zero. The underlying cause of the ~47% structural current
offset (different motor/fan capacity rating, or different current-
transformer scaling between the two fans) is an open item for Punarbasu
(see section 5) — this report does not resolve it, only avoids
mischaracterizing it as a fault.
"""


def section_parameters(cluster_config: dict) -> str:
    rel = cluster_config["relationships"]
    guard = cluster_config["ab_imbalance_guard"]
    lines = ["## 2. Parameters, thresholds and tolerances (all user-configurable)", ""]
    lines.append("Per the doc's own instruction — *\"Absolute limits should be finalized "
                  "from approved design data and reviewed healthy operation; they should "
                  "not be assumed from generic fan behavior\"* — every number below is a "
                  "reasonable configurable default pending plant validation, not a doc-given "
                  "value (only the formulas themselves, doc Table 3/5, are used verbatim).")
    lines.append("")
    lines.append("| Setting | Value | Source |")
    lines.append("|---|---|---|")
    for rel_name, cfg in rel.items():
        lines.append(f"| `{rel_name}.band_width_std` | {cfg['band_width_std']} | configurable default |")
        lines.append(f"| `{rel_name}.stratify_by` | {cfg['stratify_by']} | Step 0 decision, see 1.1 |")
        lines.append(f"| `{rel_name}.n_bins` | {cfg.get('n_bins', 5)} | configurable default |")
    lines.append(f"| `ab_imbalance_guard.comparable_duty_tolerance_pct` | {guard['comparable_duty_tolerance_pct']} | configurable default |")
    lines.append(f"| `ab_imbalance_guard.band_width_std` | {guard['band_width_std']} | configurable default |")
    lines.append(f"| `fan_running.rpm_threshold` | {cluster_config['fan_running']['rpm_threshold']} RPM | empirically chosen, see 1.4 |")
    lines.append(f"| `baseline.min_samples` | {cluster_config['baseline']['min_samples']} | configurable default, same as Cluster 1 |")
    lines.append(f"| `persistence.minutes` | {cluster_config['persistence']['minutes']} | configurable default — **not implemented this phase**, see section 6 |")
    return "\n".join(lines) + "\n"


def section_summary(results: pd.DataFrame) -> str:
    lines = ["## 3. Summary status by relationship", "",
              f"Scored across the full test window ({len(results):,} rows, unseen by training).", ""]
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
    lines = ["## 4. Worked examples — one real case per residual pattern", "",
              "Per the brief: at least one real outlier case per row of the doc's "
              "residual-interpretation table (section 6), pulled from this report's "
              "own test-window scoring — none forced; every pattern below genuinely "
              "occurs in the 2024 data (unlike Cluster 1's SHUTDOWN case, which never "
              "occurred at all — Cluster 2 has no such absent pattern to report)."]
    for pattern in PATTERN_ORDER:
        row = _example_row(results, pattern)
        lines.append(f"\n### {pattern}")
        if row is None:
            lines.append("*Did not occur in the 2024 test window.*")
            continue
        interp = row["pattern_interpretation"]
        lines.append(f"**{row['Timestamp']}** — Load {row['LOAD']:.1f}% MCR")
        lines.append(f"\n> {interp['initial_interpretation']}")
        lines.append(f">\n> Required confirmation (doc, unmodified): {interp['required_confirmation']}")
        lines.append("")
        lines.append("| variable | actual | predicted | deviation % |")
        lines.append("|---|---:|---:|---:|")
        for side in SIDES:
            for short, label in (("rpm", "RPM"), ("current", "Current"), ("igv", "IGV FB")):
                d = row[f"fan_{side.lower()}_{short}_detail"]
                if "actual" in d:
                    lines.append(f"| Fan {side} {label} | {d['actual']:.2f} | {d['predicted']:.2f} | {d.get('deviation_pct', float('nan')):+.2f}% |")
                else:
                    lines.append(f"| Fan {side} {label} | — | — | *{d.get('reason', 'n/a')}* |")
        ab = row["ab_current_imbalance_detail"]
        if "imbalance_pct" in ab:
            lines.append(f"| A/B Current Imbalance | {ab['imbalance_pct']:.2f}% | baseline {ab['baseline_mean_pct']:.2f}% ± {ab['baseline_std_pct']:.2f}% | — |")
    return "\n".join(lines) + "\n"


def section_igv_data_quality(baseline: Cluster2Baseline, test_view: pd.DataFrame) -> str:
    b_igv = test_view["PA_FAN_B_IGV_FB"].dropna()
    monthly = test_view.assign(month=test_view["Timestamp"].dt.month).groupby("month")["PA_FAN_B_IGV_FB"].agg(["mean", "std", "count"])
    monthly_lines = "\n".join(
        f"| {int(m)} | {r['mean']:.2f} | {r['std']:.2f} | {int(r['count']):,} |" for m, r in monthly.iterrows()
    )
    a_excl = baseline.excluded_counts.get("A_fan_igv", 0)
    b_excl = baseline.excluded_counts.get("B_fan_igv", 0)
    a_n = baseline.n_train_running.get("A", 0)
    b_n = baseline.n_train_running.get("B", 0)
    return f"""## 5. Fan B IGV — investigated finding, not taken at face value

Fan B IGV's outlier rate in section 3 is high. Investigated before writing
it up, same discipline as Cluster 1's stale-threshold finding — this is
NOT simply "Fan B's IGV control is unhealthy 58% of the time."

**Root cause, evidenced:**

1. Training-side: the shared `shared/data_quality.py` stale-streak
   exclusion (same detector Cluster 1 already uses, same
   `TRAINING_STALE_STREAK_ROWS=12` threshold that was originally calibrated
   for STACK_TEMPERATURE/FEGT's whole-degree quantization) excludes
   {a_excl:,}/{a_n:,} ({a_excl/a_n*100 if a_n else 0:.1f}%) of Fan A's and
   {b_excl:,}/{b_n:,} ({b_excl/b_n*100 if b_n else 0:.1f}%) of Fan B's
   IGV-FB training rows — because both fans' IGV feedback sits perfectly
   constant for weeks at a time (a genuine control characteristic, not a
   sensor fault), tripping the same "frozen value" rule. This leaves a
   thin, non-uniformly-distributed training sample.
2. Test-side: Fan B's IGV FB is a coarse, whole-integer-percent signal that
   makes discrete MONTHLY STEP CHANGES, not continuous variation:

   | month | mean | std | n |
   |---|---:|---:|---:|
{monthly_lines}

   (month 1 has 0 rows in the test window for this column — it falls
   inside the confirmed 2024-01-18 to 2024-02-11 null gap, see
   cluster2_config.yaml's `PA_FAN_B_IGV_FB` note.)

Flow does not correlate with these month-to-month steps (same reason Load
doesn't explain Flow, section 1.3), so a Flow-binned baseline — trained on
a thin, quality-filtered slice that likely reflects only 1-2 of these
months — does not generalize to the other months' different discrete IGV
settings. The result is a real, evidenced high outlier rate, but its cause
is a baseline-generalization limitation (thin/unrepresentative training
data for a step-changing signal), not necessarily 58% of the year showing
genuine IGV control abnormality. Flagged as a known limitation (section 6),
not silently corrected — a time-aware (monthly or seasonal) baseline
dimension, analogous to Cluster 1's own monthly-stratification fix for
SA/TA seasonal drift, is the most likely real fix, left for a future
revision.
"""


def section_open_items() -> str:
    return """## 6. Open items for Punarbasu / Awes

Doc's own two queries — **already on the consolidated cross-module list**
(Module 2/PAI-S02 raised the same coal-composition/fuel-quality dependency
question; not asked twice here, just noted as overlapping):

- *"If due to fuel change, if the air supply is more than usual needed for
  the same load how alert will be reliable for high RPM."* (doc section 2)
- *"Fuel GCV also be the reference [variable]?"* (doc section 2, Boiler
  Demand and Required Fan Duty)

New items from this cluster's own build:

- **PA Fan Head**: confirm no real per-fan tag exists anywhere else in the
  historian (checked exhaustively this pass, found none) and/or confirm
  whether `PA PR AT AIR BOX A/B` is a valid Head substitute for Fan A/B
  respectively (see section 1.1) — resolving this re-enables the doc's full
  3-input formula.
- **A/B Current structural offset**: why do Fan A and Fan B draw ~47%
  different current at matched RPM and comparable Flow (section 1.5)?
  Different motor/fan capacity rating, or different current-transformer
  scaling between the two fans' instrumentation? Affects whether the
  learned -47% baseline is "normal for these two different fans" or masks
  a genuine, permanent imbalance that's simply never been absent from the
  data to compare against.
- **PA PR AT AIR BOX C**: no confirmed correspondence to either fan at all
  — what is this third zone/point?
"""


def section_limitations() -> str:
    return """## 7. Known limitations — not implemented in this phase

- **Persistence / alarm timing not implemented.** The doc explicitly wants
  alarm logic to combine "residual magnitude, persistence, data quality and
  supporting variables rather than trigger on a single instantaneous
  excursion," and imbalance flagged "for a specified persistence time."
  This report scores each row independently — no rolling-persistence state
  machine. `persistence.minutes` in cluster2_config.yaml is a placeholder
  for a future revision, same scope limitation Cluster 1's report already
  carries for its own A/B trend-analysis gap.
- **Cross-cluster confirmation is out of scope.** The doc's own "Model
  boundary" note and Validation Framework's "Cross-cluster" row both expect
  PA pressure/flow, draft, and downstream air-distribution evidence from
  Clusters 3/5/8/11 to confirm an abnormal fan residual. None of those
  clusters exist yet — every `required_confirmation` string in this report
  is the doc's own text, unmodified; this validator does not attempt that
  confirmation itself.
- **Fan B IGV's high outlier rate is a baseline-generalization artifact on
  a thin, quality-filtered training sample for a step-changing signal**,
  not a confirmed real control-health finding — see section 5. Believed
  fixable with a time-aware baseline dimension in a future revision, not
  attempted this pass.
- **Quantile-based Flow bins, band_width_std, comparable-duty tolerance,
  and the fan-running RPM threshold are all configurable defaults or
  empirically-chosen values, not doc-specified numbers** (only the four
  calculated-indicator formulas and the A/B-comparability guard's
  *existence* are doc-verbatim) — see `clusters/cluster2_config.yaml` for
  every tunable field and its rationale.
- **Single fan-configuration baseline only** (both-running) — correct for
  this plant's actual 2024 operating history (section 1.4), but means the
  one real Fan-A-stop event has no dedicated baseline to be scored against;
  it correctly shows as `unknown`/large-residual rather than being forced
  through the both-running model.
- **Not wired into `server.py` or the frontend** — by design, per this
  phase's scope, same as Cluster 1.
"""


def section_conclusion(results: pd.DataFrame) -> str:
    n = len(results)
    consistent_rate = sum(
        (results[f"{c}_status"] == "consistent").sum() for c in RELATIONSHIP_COLS
    ) / (n * len(RELATIONSHIP_COLS)) * 100
    return f"""## 8. Conclusion

Cluster 2 provides a Flow-referenced (not demand/Load-referenced, see
section 1.3) normal-behaviour model for PA Fan-A and PA Fan-B
control/electrical response, scored against a STEADY-state,
fan-running-only, monthly-stratified baseline never exposed to the
{n:,}-row test window it's scored against. Across all 8 relationships,
{consistent_rate:.1f}% of (relationship x row) combinations score
`consistent`. All six of the doc's own residual-interpretation patterns
(section 6 of the doc) genuinely occur in this plant's real 2024 data,
including a coherent, physically-sensible real event (2024-03-21: Fan A
stopping while Fan B's RPM/current visibly ramp up to compensate — see
section 4's "Multiple fan residuals" example).

**Stated plainly**: because Head is unavailable and Load doesn't explain
Flow here, every "consistent"/"outlier" result above answers *whether a
fan's RPM/Current/IGV is internally consistent with its own measured
Flow* — not *whether the fan is correctly responding to boiler demand*,
which is what the doc's original `f(Fan Flow, Fan Head, Steam Flow)`
framing implied. Both are legitimate, useful questions, but they are not
the same question, and a `consistent` result here does not confirm the
fan is tracking demand correctly — only that it's behaving as its own
history at this Flow would predict.

The most consequential finding from building this cluster wasn't a fan
health signal — it was two places where applying the doc's methodology
literally, without checking real data first, would have produced a broken
or misleading model: Load does not explain Fan Flow in this plant's real
2024 operating envelope (section 1.3), and the doc's own A/B imbalance
formula would flag nearly every healthy row as an outlier without a
learned, non-zero baseline (section 1.5). Root-cause assignment for any
flagged pattern still requires the data-quality, operating-state, PA
pressure/flow, and maintenance evidence the doc itself calls for — this
cluster flags deterioration or control inconsistency early; it does not
diagnose it alone.
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    raw, full_view, baseline, results, cluster_config = run_pipeline()
    test_view = baseline.test_view

    sections = [
        section_header(raw),
        section_methodology(baseline),
        section_parameters(cluster_config),
        section_summary(results),
        section_worked_examples(results),
        section_igv_data_quality(baseline, test_view),
        section_open_items(),
        section_limitations(),
        section_conclusion(results),
    ]
    report = "\n".join(sections)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(report):,} chars)")

    write_docx(report, DOCX_OUT_PATH, title="Cluster 2 — PA Fan Performance — Validation Report")
    print(f"Wrote {DOCX_OUT_PATH}")


if __name__ == "__main__":
    main()
