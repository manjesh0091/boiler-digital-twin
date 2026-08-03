"""
clusters/cluster_features.py — Cluster 1 (Load-Flow Mass Balance) feature view.

Builds Cluster 1's raw-tag view (via shared/feature_extraction.build_feature_view)
plus every derived quantity its relationships need (Total Main Steam Flow,
Total Secondary/Tertiary/Combustion Air, and the relationship residual
metrics), off ONE already-loaded raw dataframe (see shared/raw_loader.py).
Both cluster_baseline.py (learns expected/band from STEADY history) and
cluster_validator.py (scores rows against that baseline) build off this one
function so each formula exists in exactly one place.
"""
from __future__ import annotations

import pandas as pd

from shared.feature_extraction import build_feature_view


def build_cluster_view(raw_df: pd.DataFrame, cluster_config: dict) -> pd.DataFrame:
    view = build_feature_view(raw_df, {
        "timestamp_column": cluster_config.get("timestamp_column", "Timestamp"),
        "parameters": cluster_config["members"],
    })

    # --- Table 2 (Eq 1): combine Steam Flow-A/B into one Total Main Steam Flow ---
    divisor = 2.0 if cluster_config.get("steam_flow_measurement_config", "series") == "series" else 1.0
    view["TOTAL_MAIN_STEAM_FLOW"] = (view["STEAM_FLOW_A"] + view["STEAM_FLOW_B"]) / divisor

    # --- Table 5: side totals + total combustion air ---
    view["TOTAL_SECONDARY_AIR"] = view["SA_FLOW_A"] + view["SA_FLOW_B"]
    view["TOTAL_TERTIARY_AIR"] = view["TA_FLOW_A"] + view["TA_FLOW_B"]
    view["TOTAL_COMBUSTION_AIR"] = view["TOTAL_PA_FLOW"] + view["TOTAL_SECONDARY_AIR"] + view["TOTAL_TERTIARY_AIR"]

    # --- steam_flow_ab_balance (para 15-18) ---
    ab_avg = (view["STEAM_FLOW_A"] + view["STEAM_FLOW_B"]) / 2.0
    view["STEAM_AB_DIFF_PCT"] = (view["STEAM_FLOW_A"] - view["STEAM_FLOW_B"]).abs() / ab_avg * 100.0

    # --- water_steam_balance (Table 4) — uses the raw /2 average; the
    # validator recomputes this per-row using the A/B-tiebreak-resolved
    # total steam flow instead, so this column is the "no tiebreak applied"
    # reference value only (used by cluster_baseline.py to learn the normal
    # band, and for reporting).
    view["WATER_STEAM_BALANCE_DEV_PCT"] = (
        (view["FEEDWATER_FLOW"] - view["TOTAL_MAIN_STEAM_FLOW"]) / view["TOTAL_MAIN_STEAM_FLOW"] * 100.0
    )

    # --- Table 7 (extended to TA by the same pattern) ---
    sa_avg = (view["SA_FLOW_A"] + view["SA_FLOW_B"]) / 2.0
    view["SA_SIDE_DEV_PCT"] = (view["SA_FLOW_A"] - view["SA_FLOW_B"]) / sa_avg * 100.0
    ta_avg = (view["TA_FLOW_A"] + view["TA_FLOW_B"]) / 2.0
    view["TA_SIDE_DEV_PCT"] = (view["TA_FLOW_A"] - view["TA_FLOW_B"]) / ta_avg * 100.0

    return view
