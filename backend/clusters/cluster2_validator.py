"""
clusters/cluster2_validator.py — Cluster 2 per-row relationship scoring.

Computes each Cluster 2 relationship's residual against
clusters.cluster2_baseline's STEADY-running learned bands, and classifies
each relationship's status per row as "consistent" / "outlier" / "ambiguous"
/ "unknown" -- same vocabulary and RelationshipResult shape as Cluster 1
(clusters/cluster_validator.py), imported directly rather than
reimplemented.

Per-fan relationships (fan_a_rpm, fan_a_current, fan_a_igv, and the B
equivalents): band check against clusters.cluster2_baseline, z-score-like
(|actual-predicted| <= band_width_std*std -> consistent), same pattern as
Cluster 1's _band_status. UNKNOWN when actual/predicted data is missing OR
the fan isn't running (doc: stopped-fan values don't belong in a
running-performance assessment -- scoring extends the same rule the
baseline's training filter already applies).

A/B imbalance (ab_current_imbalance, ab_rpm_imbalance): doc, "meaningful
only when both fans have comparable duty and are in a comparable control
state." Guarded per cluster2_config.yaml's ab_imbalance_guard -- AMBIGUOUS
(not scored) when duty is mismatched or either fan isn't running, same
spirit as Cluster 1's ambiguous tiebreak ("found no basis to compare,
doesn't guess").

Diagnostic interpretation (doc's residual-pattern table, section 6):
_interpret_pattern() maps a row's full set of per-fan/imbalance statuses to
the doc's own initial-interpretation + required-confirmation text, in the
doc's own priority order (broadest/most-severe pattern first). This is
surfaced as its own top-level entry in validate_row()'s return, not buried
inside a single relationship's detail -- per the brief, this cluster's
diagnostic value is largely in that interpretation text.

Cross-cluster confirmation (PA pressure/flow, draft, distribution -- doc's
own "Model boundary" table and Validation Framework's "Cross-cluster" row)
is explicitly OUT OF SCOPE: Clusters 3/5/8/11 don't exist yet. Every
required_confirmation string below is the doc's own text, unmodified --
this validator does not attempt to perform that confirmation itself.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from clusters.cluster2_baseline import Cluster2Baseline
from clusters.cluster2_features import SIDES, fan_col
from clusters.cluster_validator import AMBIGUOUS, CONSISTENT, OUTLIER, UNKNOWN, RelationshipResult

OTHER_SIDE = {"A": "B", "B": "A"}


def _is_missing(*values: float) -> bool:
    return any(v is None or pd.isna(v) for v in values)


def _band_status(value: float, mean: float, std: float, band_width_std: float) -> str:
    if pd.isna(value):
        return UNKNOWN
    if std == 0:
        return CONSISTENT if abs(value - mean) < 1e-9 else OUTLIER
    return CONSISTENT if abs(value - mean) <= band_width_std * std else OUTLIER


def validate_fan_relationship(
    row: pd.Series, side: str, relationship: str, baseline: Cluster2Baseline, rel_cfg: dict,
    running_threshold: float,
) -> RelationshipResult:
    predict_col = fan_col(side, rel_cfg["predicts_suffix"])
    actual = row[predict_col]
    rpm = row[fan_col(side, "RPM")]

    if _is_missing(actual, rpm):
        return RelationshipResult(UNKNOWN, {"reason": "missing data"})
    if rpm < running_threshold:
        return RelationshipResult(UNKNOWN, {"reason": "fan not running", "rpm": float(rpm)})

    stratify_names = rel_cfg["stratify_by"]
    stratify_values = {}
    for name in stratify_names:
        v = row[fan_col(side, name)]
        if _is_missing(v):
            return RelationshipResult(UNKNOWN, {"reason": f"missing {name}"})
        stratify_values[name] = float(v)

    try:
        band = baseline.stats_for(side, relationship, stratify_values)
    except KeyError:
        return RelationshipResult(UNKNOWN, {"reason": "no baseline coverage"})

    band_width_std = rel_cfg.get("band_width_std", 2.0)
    status = _band_status(float(actual), band.mean, band.std, band_width_std)
    detail: dict[str, Any] = {
        "actual": float(actual), "predicted": band.mean, "baseline_std": band.std, "baseline_n": band.n,
        **{f"stratify_{k}": v for k, v in stratify_values.items()},
    }
    if band.mean:
        detail["deviation_pct"] = (float(actual) - band.mean) / band.mean * 100.0

    for ref_col in rel_cfg.get("reference_only", []):
        if ref_col in row.index and not _is_missing(row[ref_col]):
            detail[f"reference_{ref_col}"] = float(row[ref_col])

    return RelationshipResult(status, detail)


def validate_ab_imbalance(
    row: pd.Series, field: str, baseline: Cluster2Baseline, guard_cfg: dict, running_threshold: float,
) -> RelationshipResult:
    """field: "CURRENT" or "RPM". Formula: (A - B) / ((A + B) / 2) * 100,
    verbatim from the doc -- guarded per ab_imbalance_guard, then scored
    against a LEARNED band (not a fixed threshold at zero -- see
    cluster2_config.yaml's ab_imbalance_guard note: this real plant's A/B
    Current Imbalance sits at a stable ~-47% structural offset, not 0%)."""
    a = row[fan_col("A", field)]
    b = row[fan_col("B", field)]
    if _is_missing(a, b):
        return RelationshipResult(UNKNOWN, {"reason": "missing data"})

    rpm_a, rpm_b = row[fan_col("A", "RPM")], row[fan_col("B", "RPM")]
    if guard_cfg.get("both_fans_must_be_running", True):
        if _is_missing(rpm_a, rpm_b) or rpm_a < running_threshold or rpm_b < running_threshold:
            return RelationshipResult(AMBIGUOUS, {"reason": "not both fans running -- imbalance not meaningful"})

    flow_a, flow_b = row[fan_col("A", "FLOW")], row[fan_col("B", "FLOW")]
    if _is_missing(flow_a, flow_b):
        return RelationshipResult(AMBIGUOUS, {"reason": "missing Flow -- cannot confirm comparable duty"})
    avg_flow = (flow_a + flow_b) / 2.0
    duty_diff_pct = abs(flow_a - flow_b) / avg_flow * 100.0 if avg_flow else float("inf")
    tol = guard_cfg.get("comparable_duty_tolerance_pct", 15.0)
    if duty_diff_pct > tol:
        return RelationshipResult(AMBIGUOUS, {
            "reason": "duty mismatch -- imbalance not meaningful per doc guard",
            "duty_diff_pct": duty_diff_pct, "tolerance_pct": tol,
        })

    avg = (a + b) / 2.0
    if not avg:
        return RelationshipResult(UNKNOWN, {"reason": "zero average, formula undefined"})
    imbalance_pct = (a - b) / avg * 100.0
    imbalance_key = "current_imbalance" if field == "CURRENT" else "rpm_imbalance"
    try:
        band = baseline.imbalance_stats(imbalance_key)
    except KeyError:
        return RelationshipResult(UNKNOWN, {"reason": "no baseline coverage for imbalance metric"})

    band_width_std = guard_cfg.get("band_width_std", 2.0)
    status = _band_status(imbalance_pct, band.mean, band.std, band_width_std)
    return RelationshipResult(status, {
        "imbalance_pct": imbalance_pct, "baseline_mean_pct": band.mean, "baseline_std_pct": band.std,
        "duty_diff_pct": duty_diff_pct,
    })


# --------------------------------------------------------------------------
# Diagnostic interpretation -- doc section 6 (Observed residual pattern ->
# Initial interpretation -> Required confirmation), applied in the doc's own
# broadest-pattern-first priority order. Text is the doc's own wording,
# unmodified, with the actual deviation direction/magnitude substituted in
# where the doc's row is agnostic to direction.
# --------------------------------------------------------------------------

def _side_broad_shift(statuses: dict[str, str]) -> bool:
    return statuses.get("rpm") == OUTLIER and statuses.get("current") == OUTLIER and statuses.get("igv") == OUTLIER


def _interpret_pattern(
    side_statuses: dict[str, dict[str, str]], ab_current_status: str, ab_rpm_status: str,
) -> dict[str, Any] | None:
    broad_sides = [s for s in SIDES if _side_broad_shift(side_statuses[s])]

    if len(broad_sides) == 2:
        return {
            "pattern": "Multiple fan residuals persist with process deviation",
            "initial_interpretation": "Higher-confidence fan/system performance issue.",
            "required_confirmation": "Escalate for cross-cluster and field verification.",
            "sides": broad_sides,
        }
    if len(broad_sides) == 1:
        return {
            "pattern": "All fan variables shift with load reference mismatch",
            "initial_interpretation": (
                "Demand input may be unreliable or operation is transient, or a Fan "
                "deterioration issue requiring investigation."
            ),
            "required_confirmation": "Validate load and steam-flow relationship before fan diagnosis.",
            "sides": broad_sides,
        }
    if ab_current_status == OUTLIER or ab_rpm_status == OUTLIER:
        return {
            "pattern": "A/B residual divergence",
            "initial_interpretation": "One fan behaves differently from its own baseline or companion fan.",
            "required_confirmation": "Confirm equal duty and compare downstream A/B air conditions.",
            "sides": [s for s in SIDES if side_statuses[s].get("rpm") == OUTLIER or side_statuses[s].get("current") == OUTLIER],
        }

    for side in SIDES:
        st = side_statuses[side]
        if st.get("current") == OUTLIER and st.get("rpm") == CONSISTENT:
            return {
                "pattern": "Current high; RPM and demand normal",
                "initial_interpretation": "Additional electrical/mechanical loading or current measurement issue.",
                "required_confirmation": "Check persistence, A/B comparison, maintenance data and related pressures/flows.",
                "sides": [side],
            }
        if st.get("rpm") == OUTLIER and st.get("current") == CONSISTENT:
            return {
                "pattern": "RPM high for normal demand",
                "initial_interpretation": "More speed is required than the learned baseline.",
                "required_confirmation": "Check PA-system resistance, air delivery and fan control state.",
                "sides": [side],
            }
        if st.get("igv") == OUTLIER and (st.get("rpm") == CONSISTENT or st.get("current") == CONSISTENT):
            return {
                "pattern": "IGV feedback abnormal for RPM/demand",
                "initial_interpretation": "Control-position or feedback relationship has changed.",
                "required_confirmation": "Verify command vs feedback, linkage/actuator condition and operating mode.",
                "sides": [side],
            }

    return None  # healthy pattern -- nothing to interpret


def validate_row(row: pd.Series, baseline: Cluster2Baseline, cluster_config: dict) -> dict[str, Any]:
    rel_cfg_map = cluster_config["relationships"]
    running_threshold = float(cluster_config["fan_running"]["rpm_threshold"])
    guard_cfg = cluster_config.get("ab_imbalance_guard", {})

    results: dict[str, RelationshipResult] = {}
    side_statuses: dict[str, dict[str, str]] = {s: {} for s in SIDES}

    for side in SIDES:
        for rel_name, short in (("fan_rpm", "rpm"), ("fan_current", "current"), ("fan_igv", "igv")):
            result = validate_fan_relationship(row, side, rel_name, baseline, rel_cfg_map[rel_name], running_threshold)
            results[f"fan_{side.lower()}_{short}"] = result
            side_statuses[side][short] = result.status

    ab_current = validate_ab_imbalance(row, "CURRENT", baseline, guard_cfg, running_threshold)
    ab_rpm = validate_ab_imbalance(row, "RPM", baseline, guard_cfg, running_threshold)
    results["ab_current_imbalance"] = ab_current
    results["ab_rpm_imbalance"] = ab_rpm

    interpretation = _interpret_pattern(side_statuses, ab_current.status, ab_rpm.status)

    return {"relationships": results, "pattern_interpretation": interpretation}


def validate_dataframe(cluster_view: pd.DataFrame, baseline: Cluster2Baseline, cluster_config: dict) -> pd.DataFrame:
    """Validate every row of a Cluster 2 feature view (see build_cluster2_view).

    Returns one row per input row with a status + detail dict per
    relationship, plus the composite pattern_interpretation (None when the
    row shows no flagged pattern).
    """
    records = []
    for row in cluster_view.itertuples(index=False):
        row_series = pd.Series(row._asdict())
        out = validate_row(row_series, baseline, cluster_config)
        record: dict[str, Any] = {"Timestamp": row_series["Timestamp"], "LOAD": row_series["LOAD"]}
        for rel_name, result in out["relationships"].items():
            record[f"{rel_name}_status"] = result.status
            record[f"{rel_name}_detail"] = result.detail
        record["pattern_interpretation"] = out["pattern_interpretation"]
        records.append(record)
    return pd.DataFrame.from_records(records)
