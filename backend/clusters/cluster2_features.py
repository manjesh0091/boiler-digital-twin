"""
clusters/cluster2_features.py — Cluster 2 (PA Fan Performance) feature view.

Builds Cluster 2's raw-tag view (via shared/feature_extraction.build_feature_view)
plus the one derived quantity its relationships need (Total Main Steam Flow,
a reference_only cross-check variable, not a model input -- see
cluster2_config.yaml). Both cluster2_baseline.py (learns expected/band from
STEADY, fan-running history) and cluster2_validator.py (scores rows against
that baseline) build off this one function so each formula exists in exactly
one place -- same pattern as Cluster 1's cluster_features.py.
"""
from __future__ import annotations

import pandas as pd

from shared.feature_extraction import build_feature_view

SIDES = ("A", "B")


def fan_col(side: str, field: str) -> str:
    """PA_FAN_{side}_{field}, e.g. fan_col("A", "RPM") -> "PA_FAN_A_RPM".
    One naming helper shared by baseline/validator so the column-naming
    convention exists in exactly one place."""
    return f"PA_FAN_{side}_{field}"


def build_cluster2_view(raw_df: pd.DataFrame, cluster2_config: dict) -> pd.DataFrame:
    view = build_feature_view(raw_df, {
        "timestamp_column": cluster2_config.get("timestamp_column", "Timestamp"),
        "parameters": cluster2_config["members"],
    })

    # --- reference_only cross-check variable (doc: "Use both load and total
    # steam flow to cross-check demand") -- same (A+B)/2 "series" combination
    # Module 1 and Cluster 1 both already use for this plant's Steam Flow-A/B
    # pair, kept consistent rather than reinvented. ---
    view["TOTAL_MAIN_STEAM_FLOW"] = (view["STEAM_FLOW_A"] + view["STEAM_FLOW_B"]) / 2.0

    return view
