"""
shared/chronological_split.py — monthly-stratified train/test split for
baseline training, to avoid training a baseline on the same data it's later
used to score (data leakage).

Splits INDEPENDENTLY WITHIN EACH CALENDAR MONTH present in the data — the
first `train_frac` of each month's own observed timestamp span goes to
train, the remainder to test — rather than a single first-`train_frac`
block of the whole year. A single early-year block (the original approach:
2024-01-18 through 2024-03-27 for train_frac=0.2) trained a baseline that
never saw a single row from June through December. Cross-checking the
Cluster 1 report under that split showed real, sustained seasonal drift in
several relationships (Total Combustion Air at a fixed load band rises
~250 -> ~265 TPH from Jan-May to Jul-Dec) that the baseline had no way to
know about, producing a wave of "outlier" rows in the back half of the year
that reflected training-window non-representativeness, not real faults.
Stratifying by month gives every month that has data an early-month
training slice, so the baseline sees the full seasonal range while still
respecting chronological order (never trains on a row using information
from later in that same month) and the dataset's real sampling gaps (a
month with zero rows, e.g. June 2024, contributes nothing to either split;
partial months, e.g. January starting the 18th, split off their own
observed span rather than an absolute calendar-day boundary that would
exclude them from training entirely).

Splits by TIMESTAMP, never row count, for the same reason as before: real
sampling gaps exist within some months too.
"""
from __future__ import annotations

import pandas as pd

EXPECTED_INTERVAL = pd.Timedelta(minutes=5)


def chronological_split(
    df: pd.DataFrame, ts_col: str = "Timestamp", train_frac: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (train_df, test_df, info). `info` documents the split method,
    per-month train/test counts, and the full dataset's gap count — meant to
    be surfaced in report output, not applied silently.
    """
    df = df.copy().reset_index(drop=True)
    df[ts_col] = pd.to_datetime(df[ts_col])
    ts = df[ts_col]

    diffs = ts.diff().dropna()
    gaps = diffs[diffs != EXPECTED_INTERVAL]

    month = ts.dt.to_period("M")
    local_start = ts.groupby(month).transform("min")
    local_end = ts.groupby(month).transform("max")
    local_cutoff = local_start + train_frac * (local_end - local_start)
    train_mask = ts < local_cutoff

    train_df = df.loc[train_mask].reset_index(drop=True)
    test_df = df.loc[~train_mask].reset_index(drop=True)

    month_summary = (
        df.assign(_month=month, _train=train_mask)
        .groupby("_month")
        .agg(n_rows=("_train", "size"), n_train=("_train", "sum"))
    )
    month_summary["n_test"] = month_summary["n_rows"] - month_summary["n_train"]
    month_breakdown = [
        {"month": str(idx), "n_rows": int(row.n_rows), "n_train": int(row.n_train), "n_test": int(row.n_test)}
        for idx, row in month_summary.iterrows()
        if row.n_rows > 0
    ]

    info = {
        "method": "monthly_stratified_timestamp_cutoff",
        "reason": (
            f"Split independently within each of {len(month_breakdown)} "
            f"calendar months with data (first {train_frac*100:.0f}% of each "
            f"month's own observed timestamp span -> train, remainder -> "
            f"test) rather than a single first-{train_frac*100:.0f}%-of-the-"
            f"year block, so the training set sees every month's operating "
            f"conditions instead of only the earliest ~2 months. "
            f"{len(gaps)} sampling gap(s) exist in the full dataset "
            f"(largest: {gaps.max() if len(gaps) else pd.Timedelta(0)}); "
            "splitting by each month's own observed span (not an absolute "
            "calendar-day boundary) means a month with no data contributes "
            "nothing to either split, and a partial month (e.g. January, "
            "which starts on the 18th) still gets a fair first-N% slice of "
            "whatever data it actually has."
        ),
        "n_gaps_in_full_dataset": int(len(gaps)),
        "start": ts.min(), "end": ts.max(),
        "train_frac_requested": train_frac,
        "n_total": int(len(df)),
        "n_train": int(len(train_df)), "n_test": int(len(test_df)),
        "train_frac_actual": (len(train_df) / len(df)) if len(df) else 0.0,
        "month_breakdown": month_breakdown,
        "train_mask": train_mask.to_numpy(),
    }
    return train_df, test_df, info
