"""
clusters/cluster4_features.py — Cluster 4 (SA Fan Performance) feature view.

Builds Cluster 4's raw-tag view (via shared/feature_extraction.build_feature_view)
plus the one derived quantity its relationships need (Total Main Steam Flow,
a reference_only cross-check variable, not a model input -- see
cluster4_config.yaml). Structurally identical to Cluster 2's
cluster2_features.py (SA_FAN_ prefix instead of PA_FAN_) -- kept as a
separate file per cluster rather than a shared generic module, same
one-file-per-cluster convention as Cluster 1/2.
"""
from __future__ import annotations

import pandas as pd

from shared.feature_extraction import build_feature_view

SIDES = ("A", "B")


def fan_col(side: str, field: str) -> str:
    """SA_FAN_{side}_{field}, e.g. fan_col("A", "SPEED") -> "SA_FAN_A_SPEED".
    One naming helper shared by baseline/validator so the column-naming
    convention exists in exactly one place."""
    return f"SA_FAN_{side}_{field}"


def build_cluster4_view(raw_df: pd.DataFrame, cluster4_config: dict) -> pd.DataFrame:
    view = build_feature_view(raw_df, {
        "timestamp_column": cluster4_config.get("timestamp_column", "Timestamp"),
        "parameters": cluster4_config["members"],
    })

    # --- reference_only cross-check variable (doc: "Use both load and total
    # steam flow to cross-check demand") -- same (A+B)/2 "series" combination
    # Module 1/Cluster 1/Cluster 2 all already use for this plant's Steam
    # Flow-A/B pair. ---
    view["TOTAL_MAIN_STEAM_FLOW"] = (view["STEAM_FLOW_A"] + view["STEAM_FLOW_B"]) / 2.0

    return view
