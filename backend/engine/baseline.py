"""
engine/baseline.py — PAI-S01 load-binned historical baseline.

Bins UNIT_LOAD into ~10% MCR bands and computes each parameter's historical
mean + standard deviation per band from module1_features.csv. This is the
real "Expected" value (+ normal band) scoring.py uses — never a hardcoded
formula. Drum Level and Furnace Draft will use the std here for z-score
based zoning; other parameters use the mean as `expected` in the existing
%-deviation formula.

Scope: only the 10 dashboard parameters in scoring.CSV_COLUMN are binned
here (not every available/derived column in the CSV) — nothing downstream
yet consumes baseline stats for the other ~20 columns (SH-stage temps, fan
currents, etc.). mode_classifier.py works off raw trend/slope, not baseline
deviation, so it doesn't need this either. Widen CSV_COLUMN in scoring.py
first if that scope needs to grow.

Bin edges are NOT uniform 10%-wide bands. This plant's real historian data
is almost entirely 90-111% MCR (median ~101.8%, 97%+ of rows >= 90%) — fewer
than 170 rows total fall below 80% load. A uniform 10%-wide scheme leaves
every sub-70% bin with 0-19 samples, so it falls back to the *global*
(all-load) mean/std — which is really the high-load average, applied to
low-load conditions. Replaying a startup/low-load stretch against that
average would trigger false Red alarms, since low-load values would be
compared against expectations the plant never actually exhibits at low load.
Bands below instead merge all sub-80% rows into one real, load-appropriate
band rather than triggering the misleading fallback; the well-populated
regime (90-111%) keeps ~10%-wide resolution.

Training-data hygiene (three independent, auditable filters, applied in
this order, BEFORE any mean/std is computed — never applied to data being
scored, only to what the baseline learns from):

  1. Monthly-stratified 20/80 split (shared/chronological_split.py) — the
     baseline trains on the first 20% of EACH calendar month's own observed
     span (Jan train-slice, Feb train-slice, ... Dec train-slice), never on
     the same rows state_builder.py later scores against it. Training on
     the full dataset and then scoring that same dataset against it is data
     leakage: every real deviation the baseline should be able to FLAG
     would already be baked into what it considers "normal." An earlier
     version of this split used a single first-20%-of-the-YEAR block
     (2024-01-18 -> 2024-03-27) instead — cross-checking the Cluster 1
     report under that split surfaced real, sustained seasonal drift in
     several relationships that a Jan-Mar-only baseline had no way to know
     about (e.g. Total Combustion Air at a fixed load band genuinely rises
     ~250 -> ~265 TPH from Jan-May to Jul-Dec), producing elevated
     "outlier" rates in the back half of the year that reflected training-
     window non-representativeness, not real faults. Splitting within each
     month instead gives the training set exposure to every month's
     operating conditions. Still split by TIMESTAMP, never row count — this
     dataset has real sampling gaps both across the year (a full missing
     month, 2024-06-01 through 2024-06-30) and within some months, and
     splitting off each month's own observed span (not an absolute
     calendar-day boundary) handles a partial month like January
     (starting the 18th) correctly.

  2. STEADY-only filtering (engine/mode_classifier.py, imported directly,
     not reimplemented) — of the training window's rows, only those
     classified STEADY are used. STARTUP/SHUTDOWN rows would corrupt the
     learned "normal" band with transient behavior; this dataset happens
     to contain zero STARTUP/SHUTDOWN rows at all (see
     mode_classifier.MODE_VALIDATION_NOTES), so in practice this only
     excludes LOW_LOAD rows within the training window — the filter is
     applied unconditionally regardless, so it's correct if that ever
     changes.

  3. Data-quality filtering (shared/data_quality.py) — ON TOP OF the
     STEADY filter, not instead of it: even a STEADY-labeled row can carry
     a brief frozen/stuck sensor reading or an implausible instrument spike
     that doesn't last long enough to flip the mode classifier's state.
     Three sub-checks, combined per parameter column: (a) frozen/stale
     streaks, same rule as state_builder.py's live per-tick stale detector;
     (b) statistically implausible spikes vs. a short rolling window;
     (c) specific rows already known to be genuine sensor faults
     (KNOWN_BAD_TIMESTAMPS), found via the Cluster 1 report's Steam
     Flow-A/B tiebreak. See shared/data_quality.py's docstring for the
     exact rules and why each exists.

Every filter's effect is recorded on the instance (self.split_info,
self.n_total, self.n_train, self.n_train_steady, self.excluded_counts) for
auditability — nothing here is a silent black-box exclusion.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from engine.mode_classifier import classify as classify_modes
from engine.scoring import CSV_COLUMN
from shared.chronological_split import chronological_split
from shared.data_quality import training_exclusion_mask

DATA_PATH = Path(__file__).parent.parent / "data" / "processed" / "module1_features.csv"
LOAD_COLUMN = "UNIT_LOAD"
TIMESTAMP_COLUMN = "Timestamp"
TRAIN_FRAC = 0.2   # first 20% of EACH calendar month (by calendar time) trains the baseline
# TODO: the [0,80) band's stats rest on a small number of training-window
# rows (this plant almost never runs below 80% MCR) — std in particular is
# a thin estimate. Revisit/re-bin once more low-load historian data is
# available.
DEFAULT_BIN_EDGES = [0.0, 80.0, 90.0, 100.0, 110.0, 120.0]  # % MCR
MIN_SAMPLES = 20  # below this, a bin's stats are considered too noisy to trust


@dataclass(frozen=True)
class BinStats:
    load_bin_low: float
    load_bin_high: float
    mean: float
    std: float
    n: int


class LoadBinnedBaseline:
    """Computes and serves mean/std per parameter, binned by UNIT_LOAD.

    Trained on the STEADY, quality-filtered rows of the first 20% of each
    calendar month only (see module docstring) — never on the data it's
    later used to score.
    """

    def __init__(self, csv_path: Path = DATA_PATH, bin_edges: list[float] = DEFAULT_BIN_EDGES, train_frac: float = TRAIN_FRAC):
        df = pd.read_csv(csv_path, parse_dates=[TIMESTAMP_COLUMN])
        if LOAD_COLUMN not in df.columns:
            raise ValueError(f"{csv_path} has no '{LOAD_COLUMN}' column to bin on")

        train_df, _test_df, split_info = chronological_split(df, TIMESTAMP_COLUMN, train_frac)
        self.split_info = split_info
        self.n_total = len(df)
        self.n_train = len(train_df)

        modes = classify_modes(train_df)
        steady_mask = (modes == "STEADY").to_numpy()
        self.n_train_steady = int(steady_mask.sum())

        train_steady = train_df.loc[steady_mask].reset_index(drop=True)

        load = train_steady[LOAD_COLUMN]
        edges = list(bin_edges)
        last_width = edges[-1] - edges[-2]
        while not load.empty and load.max() >= edges[-1]:
            edges.append(edges[-1] + last_width)
        train_steady = train_steady.assign(_load_bin=pd.cut(load, bins=edges, right=False))

        self._by_bin: dict[str, dict[pd.Interval, BinStats]] = {}
        self._global: dict[str, BinStats] = {}
        self.excluded_counts: dict[str, int] = {}

        for key, column in CSV_COLUMN.items():
            if column not in train_steady.columns:
                continue

            exclude = training_exclusion_mask(train_steady[column], train_steady[TIMESTAMP_COLUMN])
            self.excluded_counts[key] = int(exclude.sum())
            clean_col = f"_clean_{key}"
            train_steady[clean_col] = train_steady[column].where(~exclude)

            clean_all = train_steady[clean_col].dropna()
            if clean_all.empty:
                continue
            self._global[key] = BinStats(
                load_bin_low=float(edges[0]),
                load_bin_high=float(edges[-1]),
                mean=float(clean_all.mean()),
                std=float(clean_all.std(ddof=0)),
                n=int(clean_all.shape[0]),
            )

            per_bin: dict[pd.Interval, BinStats] = {}
            for interval, series in train_steady.groupby("_load_bin", observed=True)[clean_col]:
                clean = series.dropna()
                if clean.empty:
                    continue
                per_bin[interval] = BinStats(
                    load_bin_low=float(interval.left),
                    load_bin_high=float(interval.right),
                    mean=float(clean.mean()),
                    std=float(clean.std(ddof=0)),
                    n=int(clean.shape[0]),
                )
            self._by_bin[key] = per_bin

    def stats_for(self, key: str, load_pct: float, min_samples: int = MIN_SAMPLES) -> BinStats:
        """Return BinStats for `key` at `load_pct`% MCR.

        Falls back to the global (all-load) stats if no bin matches or the
        matching bin has fewer than `min_samples` rows — the historian has
        sparse coverage at the extreme ends of the load range (startup/
        shutdown), so those bins can't be trusted on their own.
        """
        per_bin = self._by_bin.get(key, {})
        for interval, stats in per_bin.items():
            if interval.left <= load_pct < interval.right and stats.n >= min_samples:
                return stats
        if key in self._global:
            return self._global[key]
        raise KeyError(f"No baseline stats available for parameter '{key}'")

    def expected(self, key: str, load_pct: float) -> float:
        return self.stats_for(key, load_pct).mean

    def std(self, key: str, load_pct: float) -> float:
        return self.stats_for(key, load_pct).std


_singleton: LoadBinnedBaseline | None = None


def get_baseline(csv_path: Path = DATA_PATH) -> LoadBinnedBaseline:
    """Lazily-built process-wide singleton — avoids CSV I/O at import time."""
    global _singleton
    if _singleton is None:
        _singleton = LoadBinnedBaseline(csv_path)
    return _singleton
