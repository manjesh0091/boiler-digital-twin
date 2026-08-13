"""
clusters/cluster4_validator.py — Cluster 4 (SA Fan Performance) per-row
relationship scoring.

Structurally identical to Cluster 2's cluster2_validator.py, adapted for two
SA-specific facts confirmed in Step 0/1:

  1. fan_igv has no real tag for SA at all (cluster4_config.yaml:
     SA_FAN_A_IGV_FB status: synthetic_needed) -- validate_fan_relationship()
     checks the relationship's `status` first and returns UNKNOWN
     immediately for fan_igv, never touching a column that doesn't exist.
  2. The doc's "All fan variables shift"/"Multiple fan residuals" patterns
     are defined around THREE variables (RPM, Current, IGV) shifting
     together. With IGV permanently unavailable for SA, "broad shift" here
     is evaluated over the TWO variables that exist (RPM + Current) instead
     of three -- an honest adaptation to the tags that actually exist, not
     a fabrication. Consequently "IGV feedback abnormal for RPM/demand" can
     never fire for Cluster 4 (igv status is always UNKNOWN, never
     OUTLIER) -- kept in the pattern-matching code for structural parity
     with Cluster 2, expected to show zero occurrences in the report, noted
     there honestly rather than silently removed.

Everything else matches Cluster 2's validator exactly: band check
(|actual-predicted| <= band_width_std*std), UNKNOWN when data's missing or
the fan isn't running (running_threshold from cluster4_config.yaml, derived
from SPEED not RPM), A/B imbalance scored against a LEARNED band (checked
fresh for SA in Step 3 -- see cluster4_baseline.py's docstring: SA's Current
imbalance also has a real non-zero offset, ~+13.7%, smaller than PA's ~47%
but still real), same doc-verbatim required_confirmation text, same
cross-cluster-out-of-scope limitation.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from clusters.cluster4_baseline import Cluster4Baseline
from clusters.cluster4_features import SIDES, fan_col
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
    row: pd.Series, side: str, relationship: str, baseline: Cluster4Baseline, rel_cfg: dict,
    running_threshold: float,
) -> RelationshipResult:
    if rel_cfg.get("status") != "available":
        return RelationshipResult(UNKNOWN, {"reason": "no real tag for this relationship -- see cluster4_config.yaml"})

    predict_col = fan_col(side, rel_cfg["predicts_suffix"])
    actual = row[predict_col]
    speed = row[fan_col(side, "SPEED")]

    if _is_missing(actual, speed):
        return RelationshipResult(UNKNOWN, {"reason": "missing data"})
    if speed < running_threshold:
        return RelationshipResult(UNKNOWN, {"reason": "fan not running", "speed": float(speed)})

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
    row: pd.Series, field: str, baseline: Cluster4Baseline, guard_cfg: dict, running_threshold: float,
) -> RelationshipResult:
    """field: "CURRENT" or "SPEED". Formula: (A - B) / ((A + B) / 2) * 100,
    verbatim from the doc -- guarded per ab_imbalance_guard, then scored
    against a LEARNED band (checked fresh for SA -- see
    cluster4_baseline.py's docstring: Current imbalance has a real ~+13.7%
    offset here too, smaller than PA's ~47% but still non-zero)."""
    a = row[fan_col("A", field)]
    b = row[fan_col("B", field)]
    if _is_missing(a, b):
        return RelationshipResult(UNKNOWN, {"reason": "missing data"})

    speed_a, speed_b = row[fan_col("A", "SPEED")], row[fan_col("B", "SPEED")]
    if guard_cfg.get("both_fans_must_be_running", True):
        if _is_missing(speed_a, speed_b) or speed_a < running_threshold or speed_b < running_threshold:
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
# Initial interpretation -> Required confirmation), doc's own broadest-
# pattern-first priority order. Text is the doc's own wording, unmodified.
# --------------------------------------------------------------------------

def _side_broad_shift(statuses: dict[str, str]) -> bool:
    """Cluster 2 (PA) requires RPM+Current+IGV all OUTLIER for a "broad
    shift". IGV doesn't exist for SA (always UNKNOWN, never OUTLIER) -- so
    for Cluster 4 this is evaluated over RPM+Current only, an honest
    adaptation to the tags that actually exist, not a fabrication of a
    third signal."""
    return statuses.get("rpm") == OUTLIER and statuses.get("current") == OUTLIER


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
                "Demand input may be unreliable, or operation is transient or Fan "
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
                "required_confirmation": "Check SA-system resistance, air delivery and fan control state.",
                "sides": [side],
            }
        if st.get("igv") == OUTLIER and (st.get("rpm") == CONSISTENT or st.get("current") == CONSISTENT):
            return {
                "pattern": "IGV feedback abnormal for RPM/demand",
                "initial_interpretation": "Control-position or feedback relationships have changed.",
                "required_confirmation": "Verify command vs feedback, linkage/actuator condition and operating mode.",
                "sides": [side],
            }

    return None  # healthy pattern -- nothing to interpret


def validate_row(row: pd.Series, baseline: Cluster4Baseline, cluster_config: dict) -> dict[str, Any]:
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
    ab_rpm = validate_ab_imbalance(row, "SPEED", baseline, guard_cfg, running_threshold)
    results["ab_current_imbalance"] = ab_current
    results["ab_rpm_imbalance"] = ab_rpm

    interpretation = _interpret_pattern(side_statuses, ab_current.status, ab_rpm.status)

    return {"relationships": results, "pattern_interpretation": interpretation}


def validate_dataframe(cluster_view: pd.DataFrame, baseline: Cluster4Baseline, cluster_config: dict) -> pd.DataFrame:
    """Validate every row of a Cluster 4 feature view (see build_cluster4_view).

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
