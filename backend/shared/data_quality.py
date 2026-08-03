"""
shared/data_quality.py — reusable data-quality filtering for BASELINE
TRAINING data only. Never apply this to rows being scored/validated — the
whole point of a baseline/validator is to still score bad-looking live or
test data, not hide it from evaluation.

Three independent mechanisms, all combined by training_exclusion_mask():

  1. Frozen/stale values — same rule as engine/state_builder.py's live
     per-tick stale-value detector (STALE_STREAK_ROWS = 3 consecutive
     identical readings = 15 min at this dataset's 5-min sampling).
     state_builder.py's own streaming counter is intentionally left as-is
     (it's stateful/per-tick, needed for the live replay loop) —
     detect_stale() here is a vectorized batch restatement of the exact
     same rule, verified to flag a fresh run of N identical values from
     its (STALE_STREAK_ROWS + 1)-th occurrence onward, same as the live
     `stale_streak >= STALE_STREAK_ROWS` check. STALE_STREAK_ROWS is
     defined here and imported back into state_builder.py so there is one
     definition, not two that could drift apart.

  2. Statistically implausible spikes — a value many rolling-window
     standard deviations from its own short centered-window median.
     Conservative by design (z_thresh defaults to 6): the goal is to catch
     sensor glitches, not trim ordinary process noise.

  3. KNOWN_BAD_TIMESTAMPS — specific rows already identified as genuine
     sensor faults by name, so those exact rows are excluded from training
     regardless of whether the generic detectors above happen to catch
     them. This list is deliberately short and manually curated — only
     rows with positive evidence, never a guess. Applied row-wide (all
     columns at that timestamp), not just the column where the fault was
     first noticed: the 2024-02-11 events coincide with a genuine 30-minute
     historian sampling gap immediately after (13:30 -> 14:00, skipping
     13:35-13:55 entirely — see shared/chronological_split.py's gap scan),
     consistent with a broader logging/instrument hiccup at that moment,
     not a single-tag glitch — so excluding the whole row is the safer
     call, at negligible cost (3 rows total).
"""
from __future__ import annotations

import pandas as pd

STALE_STREAK_ROWS = 3

# Training-exclusion uses a HIGHER streak threshold than the live detector.
# Investigating real data showed STACK_TEMPERATURE/FEGT (same raw tag,
# logged at whole-degree resolution -- 91% of values are integers, vs 0%
# for every other Module 1 parameter) trips the live 3-row/15-min rule on
# ordinary slow drift, not frozen sensors: e.g. a genuine ~9.8-hour
# overnight run at a stable value with load varying normally throughout
# (2024-03-07 23:25 -> 2024-03-08 09:10, load 96-107%, clearly not a
# frozen instrument). At 3 rows this flagged 73% of that parameter's
# STEADY training rows; 12 rows (60 min) cuts that to ~37% while still
# catching sustained freezes well past this parameter's normal repeat
# length (75th percentile run length is 8 rows / 40 min). Applied
# uniformly to every column, not just STACK_TEMPERATURE/FEGT -- this does
# not fully eliminate over-triggering on that specific parameter (a
# resolution limitation, not a pure duration one), which is called out
# explicitly wherever exclusion counts are reported rather than papered
# over. The live per-tick detector (state_builder.py, STALE_STREAK_ROWS)
# is intentionally left at 3/15min -- that's an alerting-responsiveness
# choice, a different concern from training-data hygiene.
TRAINING_STALE_STREAK_ROWS = 12

DEFAULT_SPIKE_WINDOW = 5     # rows either side, centered
DEFAULT_SPIKE_Z = 6.0        # conservative -- only catches glitches, not noise

# Found via clusters/reports/cluster1_report.py's Steam Flow-A/B tiebreak
# (see cluster1_report.md, section 3: "Steam Flow A/B Tiebreaker"): in all
# three cases Steam Flow-B implied an implausible (hundreds-of-percent)
# deviation from Feedwater Flow that Steam Flow-A did not. The single
# AMBIGUOUS row at the same 2024-10-04 event (11:40) is deliberately NOT
# included here -- there's no positive evidence it's bad, only that the
# tiebreak couldn't tell, and training exclusion shouldn't guess either.
KNOWN_BAD_TIMESTAMPS: dict[str, str] = {
    "2024-02-11 13:30:00": "Steam Flow-B glitch (Cluster 1 outlier: +965.6% implied deviation vs Feedwater; Steam Flow-A trusted)",
    "2024-02-11 14:00:00": "Steam Flow-B glitch (Cluster 1 outlier: +659.9% implied deviation vs Feedwater; Steam Flow-A trusted)",
    "2024-10-04 11:35:00": "Steam Flow-B glitch (Cluster 1 outlier: +64.0% implied deviation vs Feedwater; Steam Flow-A trusted)",
}


def detect_stale(series: pd.Series, min_streak: int = STALE_STREAK_ROWS) -> pd.Series:
    """Boolean mask: True from the `min_streak`-th consecutive identical
    reading onward. NaNs are never stale."""
    same_as_prev = (series == series.shift(1)) & series.notna()
    block_id = (~same_as_prev).cumsum()
    streak = same_as_prev.groupby(block_id).cumsum()
    return streak >= min_streak


def detect_spikes(series: pd.Series, window: int = DEFAULT_SPIKE_WINDOW, z_thresh: float = DEFAULT_SPIKE_Z) -> pd.Series:
    """Boolean mask: True where `series` deviates from its own short
    centered rolling-window median by more than `z_thresh` rolling-window
    standard deviations. A single spike inside the window doesn't move the
    window's median enough to mask itself.
    """
    rolling_median = series.rolling(window=window, center=True, min_periods=3).median()
    rolling_std = series.rolling(window=window, center=True, min_periods=3).std(ddof=0)
    z = (series - rolling_median).abs() / rolling_std.replace(0, pd.NA)
    return z.gt(z_thresh).fillna(False)


def known_bad_mask(timestamps: pd.Series) -> pd.Series:
    """Boolean mask over a Timestamp series: True for rows matching KNOWN_BAD_TIMESTAMPS."""
    bad_ts = pd.to_datetime(list(KNOWN_BAD_TIMESTAMPS.keys()))
    return pd.to_datetime(timestamps).isin(bad_ts)


def training_exclusion_mask(
    series: pd.Series, timestamps: pd.Series,
    stale_streak: int = TRAINING_STALE_STREAK_ROWS,
    spike_window: int = DEFAULT_SPIKE_WINDOW, spike_z: float = DEFAULT_SPIKE_Z,
) -> pd.Series:
    """Combined per-column "exclude this row from training" mask: stale OR
    spike OR known-bad-timestamp. Uses TRAINING_STALE_STREAK_ROWS (12, not
    the live detector's 3) by default -- see its docstring."""
    return (
        detect_stale(series, stale_streak)
        | detect_spikes(series, spike_window, spike_z)
        | known_bad_mask(timestamps)
    )
