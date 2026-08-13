
"""
clusters/cluster_baseline.py — Cluster 1 STEADY-state historical baseline.

Learns, per load bin, the expected value + normal band for each Cluster 1
relationship metric (water-steam balance deviation, A/B side balances,
total combustion air, and the per-load expectations the tiebreakers use).

Training-data hygiene (three independent, auditable filters, applied in
this order, BEFORE any mean/std is computed — never applied to the test
window, only to what the baseline learns from; see engine/baseline.py's
docstring for the full rationale, mirrored here for Cluster 1):

  1. Monthly-stratified 20/80 split (shared/chronological_split.py) —
     trains on the first 20% of EACH calendar month's own observed span,
     never on the same rows the validator later scores. Training and
     scoring on the same data is leakage: any real deviation the baseline
     should be able to flag would already be baked into what it considers
     "normal." An earlier version used a single first-20%-of-the-year block
     (2024-01-18 -> 2024-03-27) instead; that surfaced real seasonal drift
     this cluster's own report caught (Total Combustion Air and SA
     side-balance both genuinely shift across the year at a fixed load
     band), which a Jan-Mar-only baseline had no way to know about —
     monthly stratification gives training exposure to every month
     instead. The remaining ~80% (self.test_view, exposed below) is
     genuinely unseen data for clusters/cluster_validator.py. Still split
     by TIMESTAMP, never row count — real sampling gaps exist both across
     the year (a full missing month) and within some months.

  2. STEADY-only filtering, of the training window's rows — reuses
     engine/mode_classifier.py directly (imported, not reimplemented), per
     the doc's explicit warning not to mix startup/shutdown/transient data
     into training ("Important: Start-up, shutdown, trips and known
     instrument-fault periods should not be mixed with healthy
     steady-state training data"). Mode classification runs over Module
     1's own feature view, built from the SAME raw dataframe as Cluster
     1's view (shared/raw_loader.py) — both come from build_feature_view()
     with no row filtering/reordering, so their indices line up.

  3. Data-quality filtering (shared/data_quality.py), ON TOP OF the STEADY
     filter — frozen/stale streaks, statistically implausible spikes, and
     specific rows already known to be genuine sensor faults
     (KNOWN_BAD_TIMESTAMPS, found via this cluster's own earlier report:
     the 2024-02-11 Steam Flow-A/B tiebreak outliers fall inside this
     training window and are excluded here explicitly).

Load-binning uses the same custom, non-uniform bin edges and same
fallback-to-global-stats-if-too-few-samples logic as Module 1's own
engine/baseline.py, for the same reason: this plant's real data is almost
entirely 90-111% MCR.

Every filter's effect is recorded on the instance (self.split_info,
self.n_total, self.n_train, self.n_train_steady, self.excluded_counts) for
auditability.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from clusters.cluster_features import build_cluster_view
from engine.mode_classifier import classify as classify_modes
from shared.chronological_split import chronological_split
from shared.data_quality import training_exclusion_mask
from shared.feature_extraction import build_feature_view, load_config
from shared.raw_loader import load_raw

CLUSTER_CONFIG_PATH = Path(__file__).parent / "cluster_config.yaml"
MODULE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hindalco_boiler9_pai_s01_v2.yaml"
TRAIN_FRAC = 0.2

# Metrics whose STEADY-state distribution gets learned, load-binned.
# The last two (TOTAL_MAIN_STEAM_FLOW, FEEDWATER_FLOW) aren't relationships
# in their own right -- they're the per-load expectations the
# water_steam_balance tiebreak needs (doc para 21: "correlate ... with Load").
METRIC_COLUMNS = [
    "WATER_STEAM_BALANCE_DEV_PCT",
    "TOTAL_COMBUSTION_AIR",
    "SA_SIDE_DEV_PCT",
    "TA_SIDE_DEV_PCT",
    "TOTAL_MAIN_STEAM_FLOW",
    "FEEDWATER_FLOW",
]


@dataclass(frozen=True)
class BinStats:
    load_bin_low: float
    load_bin_high: float
    mean: float
    std: float
    n: int


class Cluster1Baseline:
    """Computes and serves STEADY-state mean/std per Cluster 1 metric, binned by LOAD.

    Trained on the STEADY, quality-filtered rows of the first 20% of each
    calendar month only. self.test_view holds the remaining ~80% of
    Cluster 1's feature view (unfiltered — the unseen data
    cluster_validator.py scores).
    """

    def __init__(
        self,
        raw_df: pd.DataFrame | None = None,
        cluster_config: dict | None = None,
        module_config: dict | None = None,
        train_frac: float = TRAIN_FRAC,
    ):
        self.cluster_config = cluster_config or load_config(CLUSTER_CONFIG_PATH)
        module_config = module_config or load_config(MODULE_CONFIG_PATH)
        raw_df = raw_df if raw_df is not None else load_raw()

        bcfg = self.cluster_config.get("baseline", {})
        bin_edges = bcfg.get("load_bin_edges", [0.0, 80.0, 90.0, 100.0, 110.0, 120.0])
        self.min_samples = bcfg.get("min_samples", 20)
        mode_filter = bcfg.get("mode_filter", "STEADY")

        cluster_view = build_cluster_view(raw_df, self.cluster_config)
        module_view = build_feature_view(raw_df, module_config)

        train_view, test_view, split_info = chronological_split(cluster_view, "Timestamp", train_frac)
        self.split_info = split_info
        self.n_total = len(cluster_view)
        self.n_train = len(train_view)
        self.test_view = test_view

        # module_view shares cluster_view's original index (both built off
        # the same raw_df with no row filtering/reordering) -- apply the
        # exact same per-row train mask chronological_split() computed
        # (monthly-stratified, not a single cutoff) rather than recomputing it.
        train_mask = split_info["train_mask"]
        module_train = module_view.loc[train_mask].reset_index(drop=True)
        modes = classify_modes(module_train)
        steady_mask = (modes == mode_filter).to_numpy()

        self.n_train_steady = int(steady_mask.sum())
        self.train_mode_counts = modes.value_counts().to_dict()

        train_steady = train_view.loc[steady_mask].reset_index(drop=True)
        load = train_steady["LOAD"]

        edges = list(bin_edges)
        last_width = edges[-1] - edges[-2]
        while not load.empty and load.max() >= edges[-1]:
            edges.append(edges[-1] + last_width)
        self.edges = edges
        train_steady = train_steady.assign(_load_bin=pd.cut(load, bins=edges, right=False))

        self._by_bin: dict[str, dict[pd.Interval, BinStats]] = {}
        self._global: dict[str, BinStats] = {}
        self.excluded_counts: dict[str, int] = {}

        for column in METRIC_COLUMNS:
            if column not in train_steady.columns:
                continue

            col_clean = train_steady[column].replace([float("inf"), float("-inf")], pd.NA)
            exclude = training_exclusion_mask(col_clean, train_steady["Timestamp"])
            self.excluded_counts[column] = int(exclude.sum())
            clean_col = f"_clean_{column}"
            train_steady[clean_col] = col_clean.where(~exclude)

            clean_all = train_steady[clean_col].dropna()
            if clean_all.empty:
                continue
            self._global[column] = BinStats(
                load_bin_low=float(edges[0]), load_bin_high=float(edges[-1]),
                mean=float(clean_all.mean()), std=float(clean_all.std(ddof=0)),
                n=int(clean_all.shape[0]),
            )
            per_bin: dict[pd.Interval, BinStats] = {}
            for interval, series in train_steady.groupby("_load_bin", observed=True)[clean_col]:
                clean = series.dropna()
                if clean.empty:
                    continue
                per_bin[interval] = BinStats(
                    load_bin_low=float(interval.left), load_bin_high=float(interval.right),
                    mean=float(clean.mean()), std=float(clean.std(ddof=0)),
                    n=int(clean.shape[0]),
                )
            self._by_bin[column] = per_bin

    def stats_for(self, column: str, load_pct: float) -> BinStats:
        """Return BinStats for `column` at `load_pct`% MCR.

        Falls back to global (all-STEADY-load) stats if no bin matches or
        the matching bin has fewer than min_samples rows -- same
        sparse-bin-fallback rule as Module 1's engine/baseline.py.
        """
        per_bin = self._by_bin.get(column, {})
        for interval, stats in per_bin.items():
            if interval.left <= load_pct < interval.right and stats.n >= self.min_samples:
                return stats
        if column in self._global:
            return self._global[column]
        raise KeyError(f"No baseline stats available for cluster metric '{column}'")


_singleton: Cluster1Baseline | None = None


def get_cluster1_baseline() -> Cluster1Baseline:
    """Lazily-built process-wide singleton — avoids CSV I/O at import time."""
    global _singleton
    if _singleton is None:
        _singleton = Cluster1Baseline()
    return _singleton
