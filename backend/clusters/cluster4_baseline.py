"""
clusters/cluster4_baseline.py — Cluster 4 (SA Fan Performance) STEADY-state,
fan-running historical baseline.

Structurally identical to Cluster 2's cluster2_baseline.py (SA_FAN_ prefix,
SPEED instead of RPM, one added feature: relationship-level `status` gating
so fan_igv -- no real tag exists for SA, see cluster4_config.yaml -- is
never computed, not silently fabricated). Learns, per fan side (A/B) and
relationship (fan_rpm/fan_current; fan_igv is skipped), the expected value +
normal band for that fan variable, binned by the relationship's configured
`stratify_by` columns -- N-dimensional (this cluster actually uses 2:
[FLOW, HEAD], unlike Cluster 2's 1-dimensional [FLOW] -- Head is usable for
SA, see cluster4_config.yaml's SA_FAN_A_HEAD note), same generic binning
code as Cluster 2, no changes needed to support the extra dimension.

Training-data hygiene -- same four filters as Cluster 2 (monthly-stratified
20/80 split, STEADY-only via engine/mode_classifier.py, data-quality
filtering via shared/data_quality.py, fan-running filtering per side).

NONE of Cluster 2's specific empirical findings are assumed to carry over --
every one was independently re-checked against SA's own real data:

  - Fan-configuration mix: CHECKED FRESH, same conclusion as PA reached
    independently (both fans run continuously, 99.9%+ of the year), but two
    distinct real exceptions found (not PA's single event): 2024-05-17
    ~08:35-11:30 (a genuine SA-specific single-fan-stop, Fan A down while
    Fan B compensates) and 2024-02-11 13:30 (the same already-known
    historian-gap event PA/Cluster 1 also show at this exact timestamp --
    a data-quality artifact, not an SA-specific finding).

  - stratify_by = [FLOW, HEAD], NOT the same as PA's [FLOW]-only. SA Fan
    Head (SA PR TO APH(A)/(B)) is genuinely usable, unlike PA's blocked
    case -- kept in the model.

  - Load-vs-Flow relationship: corr(Load, SA Fan Flow) = 0.42-0.43 -- much
    stronger than PA's 0.11-0.14, so this was NOT dismissed on the
    correlation number the way PA's was. Decomposed: correlation of
    MONTHLY MEAN Load vs monthly mean Flow = 0.815 (a real seasonal/slow
    co-drift exists), but correlation after removing each month's own mean
    (within-month only) drops to 0.363 (r^2 ~13%) -- a real but moderate
    within-month relationship. The range-restriction test that actually
    matters for THIS baseline's architecture -- does binning Load into
    narrow (1-percentage-point) bins, POOLED ACROSS THE WHOLE YEAR, reduce
    Flow's local conditional variance -- still comes back essentially flat
    (ratio 1.03, ~0% local variance explained), because pooling across
    months mixes together different months' different baseline Flow
    levels within the same load bin. Same decision as PA (bin by Flow, not
    Load) reached here too, but for a materially different reason: not "no
    relationship exists" but "the relationship is substantially
    seasonal/monthly-mediated and a non-time-aware Load-bin can't exploit
    it" -- see reports/cluster4_report.md section 1.3 for the full
    numbers, not copy-pasted from Cluster 2's report.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from clusters.cluster4_features import SIDES, build_cluster4_view, fan_col
from engine.mode_classifier import classify as classify_modes
from shared.chronological_split import chronological_split
from shared.data_quality import training_exclusion_mask
from shared.feature_extraction import build_feature_view, load_config
from shared.raw_loader import load_raw

CLUSTER4_CONFIG_PATH = Path(__file__).parent / "cluster4_config.yaml"
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


class Cluster4Baseline:
    """Computes and serves STEADY-state, fan-running mean/std per (side,
    relationship), binned by that relationship's configured stratify_by
    columns. Relationships with `status` != "available" (fan_igv) are
    skipped entirely -- no bins, no global stats, no fabricated values.

    Trained on the STEADY, running, quality-filtered rows of the first 20%
    of each calendar month only. self.test_view holds the remaining ~80%
    of Cluster 4's feature view (unfiltered — the unseen data
    cluster4_validator.py scores).
    """

    def __init__(
        self,
        raw_df: pd.DataFrame | None = None,
        cluster_config: dict | None = None,
        module_config: dict | None = None,
        train_frac: float = TRAIN_FRAC,
    ):
        self.cluster_config = cluster_config or load_config(CLUSTER4_CONFIG_PATH)
        module_config = module_config or load_config(MODULE_CONFIG_PATH)
        raw_df = raw_df if raw_df is not None else load_raw()

        bcfg = self.cluster_config.get("baseline", {})
        self.min_samples = bcfg.get("min_samples", 20)
        mode_filter = bcfg.get("mode_filter", "STEADY")
        self.running_threshold = float(self.cluster_config["fan_running"]["rpm_threshold"])

        cluster_view = build_cluster4_view(raw_df, self.cluster_config)
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
            running_mask = train_steady[fan_col(side, "SPEED")] >= self.running_threshold
            side_train = train_steady.loc[running_mask].reset_index(drop=True)
            self.n_train_running[side] = int(len(side_train))

            for rel_name in RELATIONSHIPS:
                rel_cfg = rel_cfg_map[rel_name]
                if rel_cfg.get("status") != "available":
                    continue  # fan_igv: no real tag for SA -- never computed, see cluster4_config.yaml

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
        # duty. Found empirically (Step 3, checked fresh for SA): A/B
        # Current Imbalance sits at a stable ~+13.7% offset (IQR +11.9% to
        # +16.2%) -- smaller in magnitude than PA's ~-47%, but still clearly
        # non-zero, so the SAME learned-baseline treatment is used (not a
        # fixed threshold at zero), for consistency and because a fixed
        # zero-centered threshold would still bias-flag most healthy rows.
        # Speed imbalance, like PA's RPM imbalance, genuinely IS centered
        # near zero (mean 0.03%) -- both metrics still get the same learned
        # treatment for architectural consistency, not special-cased. ----
        guard_cfg = self.cluster_config.get("ab_imbalance_guard", {})
        both_running = (
            (train_steady[fan_col("A", "SPEED")] >= self.running_threshold)
            & (train_steady[fan_col("B", "SPEED")] >= self.running_threshold)
        )
        flow_a, flow_b = train_steady[fan_col("A", "FLOW")], train_steady[fan_col("B", "FLOW")]
        avg_flow = (flow_a + flow_b) / 2.0
        duty_diff_pct = (flow_a - flow_b).abs() / avg_flow.replace(0, pd.NA) * 100.0
        comparable_duty = duty_diff_pct <= guard_cfg.get("comparable_duty_tolerance_pct", 15.0)
        guard_ok = (both_running & comparable_duty).fillna(False)
        imbalance_train = train_steady.loc[guard_ok]

        for field, imbalance_key in (("CURRENT", "current_imbalance"), ("SPEED", "rpm_imbalance")):
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
            raise KeyError(f"No baseline stats available for Cluster 4 AB {field}")
        return self._global[key]

    def stats_for(self, side: str, relationship: str, stratify_values: dict[str, float]) -> BinStats:
        """Return BinStats for `relationship` on fan `side` at the given
        stratify-column values (e.g. {"FLOW": 61.2, "HEAD": 552.0}).

        Falls back to global (all-STEADY-running) stats if no bin matches
        or the matching bin has fewer than min_samples rows -- same
        sparse-bin-fallback rule as Cluster 2/Module 1's baselines.
        """
        key = (side, relationship)
        rel_cfg = self.cluster_config["relationships"][relationship]
        stratify_names = rel_cfg["stratify_by"]
        by_bin = self._by_bin.get(key, {})

        for bin_tuple, stats in by_bin.items():
            if stats.n < self.min_samples:
                continue
            matched = True
            for i, name in enumerate(stratify_names):
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
        raise KeyError(f"No baseline stats available for Cluster 4 side={side} relationship={relationship}")


_singleton: Cluster4Baseline | None = None


def get_cluster4_baseline() -> Cluster4Baseline:
    """Lazily-built process-wide singleton — avoids CSV I/O at import time."""
    global _singleton
    if _singleton is None:
        _singleton = Cluster4Baseline()
    return _singleton
