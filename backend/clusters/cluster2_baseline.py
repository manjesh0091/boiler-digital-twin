"""
clusters/cluster2_baseline.py — Cluster 2 STEADY-state, fan-running historical baseline.

Learns, per fan side (A/B) and relationship (fan_rpm/fan_igv/fan_current),
the expected value + normal band for that fan variable, binned by the
relationship's configured `stratify_by` columns (cluster2_config.yaml) --
currently just PA_FAN_{side}_FLOW (Head is dropped, see cluster2_config.yaml's
PA_FAN_A_HEAD note), but the binning below is written generically over
however many stratify_by columns a relationship declares, N-dimensional, not
hardcoded to one -- so adding Head back later is a config-only change (add
"HEAD" to a relationship's stratify_by list once a real per-fan Head tag
exists), no code change here.

Training-data hygiene -- same three filters as Cluster 1
(clusters/cluster_baseline.py), PLUS a fourth new for this cluster:

  1. Monthly-stratified 20/80 split (shared/chronological_split.py) -- same
     leakage-avoidance rationale as Cluster 1's own docstring.
  2. STEADY-only filtering -- reuses engine/mode_classifier.py directly, per
     the doc's own repeated warning ("Separate steady-state and transient
     data").
  3. Data-quality filtering (shared/data_quality.py) -- frozen/stale
     streaks, statistically implausible spikes.
  4. NEW for Cluster 2 -- fan-running filtering: doc, "Retain fan
     running/stopped status if available; remove stopped-fan values from
     the running-performance model." No real status tag exists (Step 0
     finding) -- derived from RPM via fan_running.rpm_threshold in
     cluster2_config.yaml (500 RPM, chosen empirically -- see that config's
     comment), applied PER SIDE (a stopped Fan A doesn't disqualify Fan B's
     own training rows, and vice versa).

Fan-configuration split (Fan-A-only / Fan-B-only / both / changeover) --
CHECKED EMPIRICALLY, not assumed (Step 2 instruction). This plant runs both
PA fans essentially continuously through 2024 (99.93%+ of rows have both
fans' RPM above the running threshold); the only exception is a single
~3-hour Fan-A event on 2024-03-21. There is no meaningful training
population for any configuration other than "both running" -- so no
separate per-configuration baselines are built (would have ~0 training
data), matching cluster2_config.yaml's `fan_configuration_mix:
both_running_only` and the doc's own "if this plant always runs both fans,
skip building configuration-specific baselines" guidance (paraphrased from
the brief this cluster was built from).

Bin edges are QUANTILE-based (n_bins per relationship, cluster2_config.yaml),
computed from the STEADY+running training data itself, not fixed percentage
edges like Module 1/Cluster 1's LOAD bins -- checked empirically (Step 0/1):
Load and PA Fan Flow correlate only ~0.11-0.14 in this real dataset (Load's
own range is compressed to ~87-111% MCR almost all year, leaving little
variance to explain), while Fan-A Flow and Fan-B Flow correlate 0.994 with
EACH OTHER -- so stratifying by each fan's OWN Flow (the doc's actual
Table-3 input) captures far more of the real variation than reusing Module
1's load bins would, and Flow has no natural "% of something" scale the way
Load does, so quantile-based edges (adapting to each fan's own observed
range) are used instead of hand-picked absolute thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from clusters.cluster2_features import SIDES, build_cluster2_view, fan_col
from engine.mode_classifier import classify as classify_modes
from shared.chronological_split import chronological_split
from shared.data_quality import training_exclusion_mask
from shared.feature_extraction import build_feature_view, load_config
from shared.raw_loader import load_raw

CLUSTER2_CONFIG_PATH = Path(__file__).parent / "cluster2_config.yaml"
MODULE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hindalco_boiler9_pai_s01_v2.yaml"
TRAIN_FRAC = 0.2

RELATIONSHIPS = ("fan_rpm", "fan_igv", "fan_current")


@dataclass(frozen=True)
class BinStats:
    bin_key: tuple  # one pd.Interval per stratify_by column, in config order
    mean: float
    std: float
    n: int


def _quantile_edges(series: pd.Series, n_bins: int) -> list[float]:
    """n_bins quantile-based edges from `series`, outer edges widened to
    +/-inf so any scoring-time value (including outside the training range)
    always falls in some bin. Dedupes consecutive equal edges (can happen
    on sparse/discrete-looking data)."""
    qs = np.linspace(0.0, 1.0, n_bins + 1)
    raw_edges = series.quantile(qs).tolist()
    edges = [-np.inf] + raw_edges[1:-1] + [np.inf]
    deduped = [edges[0]]
    for e in edges[1:]:
        if e > deduped[-1]:
            deduped.append(e)
    if len(deduped) < 2:
        deduped = [-np.inf, np.inf]
    return deduped


class Cluster2Baseline:
    """Computes and serves STEADY-state, fan-running mean/std per (side,
    relationship), binned by that relationship's configured stratify_by
    columns.

    Trained on the STEADY, running, quality-filtered rows of the first 20%
    of each calendar month only. self.test_view holds the remaining ~80%
    of Cluster 2's feature view (unfiltered — the unseen data
    cluster2_validator.py scores).
    """

    def __init__(
        self,
        raw_df: pd.DataFrame | None = None,
        cluster_config: dict | None = None,
        module_config: dict | None = None,
        train_frac: float = TRAIN_FRAC,
    ):
        self.cluster_config = cluster_config or load_config(CLUSTER2_CONFIG_PATH)
        module_config = module_config or load_config(MODULE_CONFIG_PATH)
        raw_df = raw_df if raw_df is not None else load_raw()

        bcfg = self.cluster_config.get("baseline", {})
        self.min_samples = bcfg.get("min_samples", 20)
        mode_filter = bcfg.get("mode_filter", "STEADY")
        self.rpm_running_threshold = float(self.cluster_config["fan_running"]["rpm_threshold"])

        cluster_view = build_cluster2_view(raw_df, self.cluster_config)
        module_view = build_feature_view(raw_df, module_config)

        train_view, test_view, split_info = chronological_split(cluster_view, "Timestamp", train_frac)
        self.split_info = split_info
        self.n_total = len(cluster_view)
        self.n_train = len(train_view)
        self.test_view = test_view

        # module_view shares cluster_view's original index (both built off
        # the same raw_df with no row filtering/reordering) -- apply the
        # exact same per-row train mask chronological_split() computed.
        train_mask = split_info["train_mask"]
        module_train = module_view.loc[train_mask].reset_index(drop=True)
        modes = classify_modes(module_train)
        steady_mask = (modes == mode_filter).to_numpy()

        self.n_train_steady = int(steady_mask.sum())
        self.train_mode_counts = modes.value_counts().to_dict()

        train_steady = train_view.loc[steady_mask].reset_index(drop=True)

        self._by_bin: dict[tuple[str, str], dict[tuple, BinStats]] = {}
        self._global: dict[tuple[str, str], BinStats] = {}
        self._bin_edges: dict[tuple[str, str], dict[str, list[float]]] = {}
        self.excluded_counts: dict[str, int] = {}
        self.n_train_running: dict[str, int] = {}

        rel_cfg_map = self.cluster_config["relationships"]

        for side in SIDES:
            running_mask = train_steady[fan_col(side, "RPM")] >= self.rpm_running_threshold
            side_train = train_steady.loc[running_mask].reset_index(drop=True)
            self.n_train_running[side] = int(len(side_train))

            for rel_name in RELATIONSHIPS:
                rel_cfg = rel_cfg_map[rel_name]
                predict_col = fan_col(side, rel_cfg["predicts_suffix"])
                stratify_names = rel_cfg["stratify_by"]
                stratify_cols = [fan_col(side, s) for s in stratify_names]
                n_bins = int(rel_cfg.get("n_bins", 5))
                key = (side, rel_name)

                col_clean = side_train[predict_col].replace([float("inf"), float("-inf")], pd.NA)
                exclude = training_exclusion_mask(col_clean, side_train["Timestamp"])
                self.excluded_counts[f"{side}_{rel_name}"] = int(exclude.sum())
                clean = col_clean.where(~exclude)

                valid = clean.notna()
                for c in stratify_cols:
                    valid &= side_train[c].notna()
                clean_valid = clean[valid]
                if clean_valid.empty:
                    continue

                self._global[key] = BinStats(
                    bin_key=(), mean=float(clean_valid.mean()), std=float(clean_valid.std(ddof=0)),
                    n=int(clean_valid.shape[0]),
                )

                edges_per_col = {c: _quantile_edges(side_train.loc[valid, c], n_bins) for c in stratify_cols}
                self._bin_edges[key] = edges_per_col

                bin_frame = pd.DataFrame({"_val": clean_valid})
                for c in stratify_cols:
                    bin_frame[c] = pd.cut(side_train.loc[valid, c], bins=edges_per_col[c])

                per_bin: dict[tuple, BinStats] = {}
                for bin_tuple, group in bin_frame.groupby(stratify_cols, observed=True):
                    bt = bin_tuple if isinstance(bin_tuple, tuple) else (bin_tuple,)
                    g = group["_val"].dropna()
                    if g.empty:
                        continue
                    per_bin[bt] = BinStats(bin_key=bt, mean=float(g.mean()), std=float(g.std(ddof=0)), n=int(g.shape[0]))
                self._by_bin[key] = per_bin

        # ---- A/B imbalance baselines -- GLOBAL only (no stratification),
        # learned from rows where BOTH fans are running and have comparable
        # duty (same guard the validator applies at scoring time -- see
        # cluster2_config.yaml's ab_imbalance_guard note). Found empirically
        # (Step 3): A/B Current Imbalance sits at a stable ~-47% structural
        # offset in this real plant, NOT centered at 0% -- learning that
        # offset here is what makes the validator's band check meaningful
        # instead of a permanent false alarm. ----
        guard_cfg = self.cluster_config.get("ab_imbalance_guard", {})
        both_running = (
            (train_steady[fan_col("A", "RPM")] >= self.rpm_running_threshold)
            & (train_steady[fan_col("B", "RPM")] >= self.rpm_running_threshold)
        )
        flow_a, flow_b = train_steady[fan_col("A", "FLOW")], train_steady[fan_col("B", "FLOW")]
        avg_flow = (flow_a + flow_b) / 2.0
        duty_diff_pct = (flow_a - flow_b).abs() / avg_flow.replace(0, pd.NA) * 100.0
        comparable_duty = duty_diff_pct <= guard_cfg.get("comparable_duty_tolerance_pct", 15.0)
        guard_ok = (both_running & comparable_duty).fillna(False)
        imbalance_train = train_steady.loc[guard_ok]

        for field, imbalance_key in (("CURRENT", "current_imbalance"), ("RPM", "rpm_imbalance")):
            a, b = imbalance_train[fan_col("A", field)], imbalance_train[fan_col("B", field)]
            avg = (a + b) / 2.0
            imbalance_pct = ((a - b) / avg.replace(0, pd.NA) * 100.0).dropna()
            key = ("AB", imbalance_key)
            if imbalance_pct.empty:
                continue
            exclude = training_exclusion_mask(imbalance_pct, imbalance_train.loc[imbalance_pct.index, "Timestamp"])
            self.excluded_counts[f"AB_{imbalance_key}"] = int(exclude.sum())
            clean = imbalance_pct[~exclude]
            if clean.empty:
                continue
            self._global[key] = BinStats(
                bin_key=(), mean=float(clean.mean()), std=float(clean.std(ddof=0)), n=int(clean.shape[0]),
            )

    def imbalance_stats(self, field: str) -> BinStats:
        """field: "current_imbalance" or "rpm_imbalance". Global-only (no
        stratification) -- see the imbalance-baseline note in __init__."""
        key = ("AB", field)
        if key not in self._global:
            raise KeyError(f"No baseline stats available for Cluster 2 AB {field}")
        return self._global[key]

    def stats_for(self, side: str, relationship: str, stratify_values: dict[str, float]) -> BinStats:
        """Return BinStats for `relationship` on fan `side` at the given
        stratify-column values (e.g. {"FLOW": 39.2}).

        Falls back to global (all-STEADY-running) stats if no bin matches
        or the matching bin has fewer than min_samples rows -- same
        sparse-bin-fallback rule as Module 1/Cluster 1's baselines.
        """
        key = (side, relationship)
        rel_cfg = self.cluster_config["relationships"][relationship]
        stratify_names = rel_cfg["stratify_by"]
        edges_per_col = self._bin_edges.get(key, {})
        by_bin = self._by_bin.get(key, {})

        for bin_tuple, stats in by_bin.items():
            if stats.n < self.min_samples:
                continue
            matched = True
            for i, name in enumerate(stratify_names):
                col = fan_col(side, name)
                val = stratify_values.get(name)
                if val is None or pd.isna(val):
                    matched = False
                    break
                interval = bin_tuple[i]
                if val not in interval:
                    matched = False
                    break
            if matched:
                return stats

        if key in self._global:
            return self._global[key]
        raise KeyError(f"No baseline stats available for Cluster 2 side={side} relationship={relationship}")


_singleton: Cluster2Baseline | None = None


def get_cluster2_baseline() -> Cluster2Baseline:
    """Lazily-built process-wide singleton — avoids CSV I/O at import time."""
    global _singleton
    if _singleton is None:
        _singleton = Cluster2Baseline()
    return _singleton
