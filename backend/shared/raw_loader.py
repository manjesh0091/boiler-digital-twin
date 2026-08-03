"""
shared/raw_loader.py — single shared raw-CSV load for the whole backend.

Loads the full Hindalco historian export (all ~103 columns, untouched) into
memory once. Module 1's feature extraction and the Cluster validation code
both build their config-specific views off this one load (via
shared/feature_extraction.py's build_feature_view), rather than each
re-reading the CSV independently.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RAW_CSV_PATH = Path(__file__).parent.parent / "data" / "raw" / "boiler9_cleaned_2024.csv"

_cache: dict[Path, pd.DataFrame] = {}


def load_raw(csv_path: Path | str = RAW_CSV_PATH) -> pd.DataFrame:
    """Load the raw historian CSV, cached per path so repeated callers in the
    same process don't re-parse the file. Returns a copy so callers can
    freely mutate their own view without corrupting the shared cache.
    """
    csv_path = Path(csv_path)
    if csv_path not in _cache:
        _cache[csv_path] = pd.read_csv(csv_path)
    return _cache[csv_path].copy()
