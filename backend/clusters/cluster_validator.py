"""
clusters/cluster_validator.py — Cluster 1 per-row relationship scoring.

Computes each Cluster 1 relationship's residual against
clusters.cluster_baseline's STEADY-state learned bands, and classifies each
relationship's status per row as "consistent" / "outlier" / "ambiguous" /
"unknown" (missing data).

Two relationships implement the doc's explicit tiebreakers. Both follow the
SAME pattern the doc specifies in each case: compare two candidate values'
distance from a baseline expectation, trust whichever is closer, and mark
the relationship "ambiguous" (never guess) when the two candidates are too
close to call. No other tiebreak heuristic is applied beyond what the doc
describes.

  steam_flow_ab_balance (validate_steam_flow_ab):
    doc: "In case of Eq 1 Correlate both readings acceptable variation 3%
    ... In case two readings differ Correlate with Feed Flow." When A and B
    disagree beyond tolerance_pct, each candidate is plugged in as Total
    Main Steam Flow and the resulting water-steam-balance deviation is
    compared against the learned normal band for that metric at this load;
    whichever candidate lands closer to the band center is trusted.

  water_steam_balance (validate_water_steam_balance):
    doc para 21: "There is a relationship between Steam Flow, Feed Water
    Flow and Load. In case Steam Flow and Feed Flow are not matching both
    values should be correlated with Load. The value matching with load
    should be considered and other will be corrected." When the resolved
    Total Steam Flow and Feedwater Flow disagree beyond the learned normal
    band, each is compared against ITS OWN load-baseline expectation;
    whichever is closer to what Load predicts is trusted.

air_vs_load_envelope, sa_ab_balance and ta_ab_balance have no tiebreak
specified in the doc -- they're scored consistent/outlier against their
learned band only (the doc explicitly defers further diagnosis on an
out-of-band air reading to "a different cluster").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from clusters.cluster_baseline import Cluster1Baseline

UNKNOWN = "unknown"
CONSISTENT = "consistent"
OUTLIER = "outlier"
AMBIGUOUS = "ambiguous"


@dataclass
class RelationshipResult:
    status: str
    detail: dict[str, Any] = field(default_factory=dict)


def _is_missing(*values: float) -> bool:
    return any(v is None or pd.isna(v) for v in values)


def _band_status(value: float, mean: float, std: float, band_width_std: float) -> str:
    if pd.isna(value):
        return UNKNOWN
    if std == 0:
        return CONSISTENT if abs(value - mean) < 1e-9 else OUTLIER
    return CONSISTENT if abs(value - mean) <= band_width_std * std else OUTLIER


def validate_steam_flow_ab(row: pd.Series, baseline: Cluster1Baseline, rel_cfg: dict) -> RelationshipResult:
    ab_diff_pct = row["STEAM_AB_DIFF_PCT"]
    if _is_missing(ab_diff_pct):
        return RelationshipResult(UNKNOWN, {"ab_diff_pct": ab_diff_pct})

    tol = rel_cfg["tolerance_pct"]
    if ab_diff_pct <= tol:
        return RelationshipResult(CONSISTENT, {"ab_diff_pct": ab_diff_pct})

    load, fw = row["LOAD"], row["FEEDWATER_FLOW"]
    a, b = row["STEAM_FLOW_A"], row["STEAM_FLOW_B"]
    detail: dict[str, Any] = {"ab_diff_pct": ab_diff_pct}

    if _is_missing(load, fw, a, b) or a == 0 or b == 0:
        return RelationshipResult(AMBIGUOUS, detail)

    wsb = baseline.stats_for("WATER_STEAM_BALANCE_DEV_PCT", load)
    dev_a = (fw - a) / a * 100.0
    dev_b = (fw - b) / b * 100.0
    dist_a = abs(dev_a - wsb.mean)
    dist_b = abs(dev_b - wsb.mean)
    detail.update({
        "dev_a_vs_fw_pct": dev_a, "dev_b_vs_fw_pct": dev_b,
        "wsb_baseline_mean_pct": wsb.mean, "wsb_baseline_std_pct": wsb.std,
    })

    margin = rel_cfg.get("tiebreak_ambiguous_margin_pct", 15.0)
    if abs(dist_a - dist_b) < margin:
        return RelationshipResult(AMBIGUOUS, detail)

    trusted = "A" if dist_a < dist_b else "B"
    detail["trusted_side"] = trusted
    detail["flagged_side"] = "B" if trusted == "A" else "A"
    return RelationshipResult(OUTLIER, detail)


def validate_water_steam_balance(
    load: float, fw: float, resolved_total_steam: float | None,
    baseline: Cluster1Baseline, rel_cfg: dict,
) -> RelationshipResult:
    if _is_missing(load, fw, resolved_total_steam) or resolved_total_steam == 0:
        return RelationshipResult(UNKNOWN, {})

    dev_pct = (fw - resolved_total_steam) / resolved_total_steam * 100.0
    band = baseline.stats_for("WATER_STEAM_BALANCE_DEV_PCT", load)
    band_width_std = rel_cfg.get("band_width_std", 2.0)
    detail: dict[str, Any] = {
        "deviation_pct": dev_pct, "baseline_mean_pct": band.mean, "baseline_std_pct": band.std,
    }
    status = _band_status(dev_pct, band.mean, band.std, band_width_std)
    if status != OUTLIER:
        return RelationshipResult(status, detail)

    # tiebreak: doc para 21 -- correlate Total Steam Flow and Feedwater Flow
    # each against what Load's own baseline predicts for them.
    steam_band = baseline.stats_for("TOTAL_MAIN_STEAM_FLOW", load)
    fw_band = baseline.stats_for("FEEDWATER_FLOW", load)
    if steam_band.mean == 0 or fw_band.mean == 0:
        return RelationshipResult(AMBIGUOUS, detail)

    steam_dev_from_load = abs(resolved_total_steam - steam_band.mean) / steam_band.mean * 100.0
    fw_dev_from_load = abs(fw - fw_band.mean) / fw_band.mean * 100.0
    detail["steam_dev_from_load_pct"] = steam_dev_from_load
    detail["fw_dev_from_load_pct"] = fw_dev_from_load

    margin = rel_cfg.get("tiebreak_ambiguous_margin_pct", 15.0)
    if abs(steam_dev_from_load - fw_dev_from_load) < margin:
        return RelationshipResult(AMBIGUOUS, detail)

    trusted = "steam_flow" if steam_dev_from_load < fw_dev_from_load else "feedwater_flow"
    detail["trusted"] = trusted
    detail["flagged_for_correction"] = "feedwater_flow" if trusted == "steam_flow" else "steam_flow"
    return RelationshipResult(OUTLIER, detail)


def validate_air_vs_load(load: float, total_air: float, baseline: Cluster1Baseline, rel_cfg: dict) -> RelationshipResult:
    if _is_missing(load, total_air):
        return RelationshipResult(UNKNOWN, {})
    band = baseline.stats_for("TOTAL_COMBUSTION_AIR", load)
    band_width_std = rel_cfg.get("band_width_std", 2.0)
    status = _band_status(total_air, band.mean, band.std, band_width_std)
    return RelationshipResult(status, {
        "total_combustion_air": total_air, "baseline_mean": band.mean, "baseline_std": band.std,
    })


def validate_side_balance(load: float, side_dev_pct: float, metric_column: str, baseline: Cluster1Baseline, rel_cfg: dict) -> RelationshipResult:
    if _is_missing(load, side_dev_pct):
        return RelationshipResult(UNKNOWN, {})
    band = baseline.stats_for(metric_column, load)
    band_width_std = rel_cfg.get("band_width_std", 2.0)
    status = _band_status(side_dev_pct, band.mean, band.std, band_width_std)
    return RelationshipResult(status, {
        "side_dev_pct": side_dev_pct, "baseline_mean_pct": band.mean, "baseline_std_pct": band.std,
    })


def validate_row(row: pd.Series, baseline: Cluster1Baseline, cluster_config: dict) -> dict[str, RelationshipResult]:
    rel = cluster_config["relationships"]
    load = row["LOAD"]

    # Total Steam Flow used downstream (water_steam_balance below) depends
    # on how the A/B tiebreak resolved:
    #   OUTLIER    -> the trusted side alone (A or B), per the tiebreak.
    #   CONSISTENT -> row["TOTAL_MAIN_STEAM_FLOW"], the plain (A+B)/2
    #                 average -- both readings agree, so averaging is the
    #                 natural combination.
    #   AMBIGUOUS  -> ALSO row["TOTAL_MAIN_STEAM_FLOW"], the same plain
    #                 average as the consistent case. This is a neutral
    #                 fallback, not a resolution: the tiebreak found no
    #                 basis to prefer A or B, so downstream code doesn't
    #                 invent one either -- it uses the same combination it
    #                 would use if the readings had agreed, rather than
    #                 arbitrarily picking a side. water_steam_balance's own
    #                 status/detail for that row still reflects whatever
    #                 residual this average produces; nothing here hides
    #                 the ambiguity from a consumer inspecting the row.
    steam_ab = validate_steam_flow_ab(row, baseline, rel["steam_flow_ab_balance"])
    if steam_ab.status == OUTLIER:
        trusted = steam_ab.detail["trusted_side"]
        resolved_total_steam = row["STEAM_FLOW_A"] if trusted == "A" else row["STEAM_FLOW_B"]
    else:
        resolved_total_steam = row["TOTAL_MAIN_STEAM_FLOW"]

    water_steam = validate_water_steam_balance(load, row["FEEDWATER_FLOW"], resolved_total_steam, baseline, rel["water_steam_balance"])
    air = validate_air_vs_load(load, row["TOTAL_COMBUSTION_AIR"], baseline, rel["air_vs_load_envelope"])
    sa_ab = validate_side_balance(load, row["SA_SIDE_DEV_PCT"], "SA_SIDE_DEV_PCT", baseline, rel["sa_ab_balance"])
    ta_ab = validate_side_balance(load, row["TA_SIDE_DEV_PCT"], "TA_SIDE_DEV_PCT", baseline, rel["ta_ab_balance"])

    return {
        "steam_flow_ab_balance": steam_ab,
        "water_steam_balance": water_steam,
        "air_vs_load_envelope": air,
        "sa_ab_balance": sa_ab,
        "ta_ab_balance": ta_ab,
    }


def validate_dataframe(cluster_view: pd.DataFrame, baseline: Cluster1Baseline, cluster_config: dict) -> pd.DataFrame:
    """Validate every row of a Cluster 1 feature view (see build_cluster_view).

    Returns one row per input row with a status + detail dict per relationship.
    """
    records = []
    for row in cluster_view.itertuples(index=False):
        row_series = pd.Series(row._asdict())
        results = validate_row(row_series, baseline, cluster_config)
        record = {"Timestamp": row_series["Timestamp"], "LOAD": row_series["LOAD"]}
        for rel_name, result in results.items():
            record[f"{rel_name}_status"] = result.status
            record[f"{rel_name}_detail"] = result.detail
        records.append(record)
    return pd.DataFrame.from_records(records)
