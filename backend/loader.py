"""
loader.py — PAI-S01 Feature Extractor CLI
======================================
Thin CLI wrapper around shared/raw_loader.py + shared/feature_extraction.py.
Reads the raw Hindalco Boiler-9 historian CSV, applies the tag-mapping
config (hindalco_boiler9_pai_s01_v2.yaml), and writes a single clean
CSV with one column per Module-1 logical parameter — ready for the
backend computation engine (baseline.py, scoring.py).

The actual raw-load and extraction logic lives in shared/ so Module 1's
offline feature build and the Cluster validation code both build off one
shared raw load instead of each re-reading/re-deriving independently.

Usage:
    python loader.py --csv boiler9_cleaned_2024.csv --config hindalco_boiler9_pai_s01_v2.yaml --out module1_features.csv
"""

import argparse
import sys

from shared.feature_extraction import build_feature_view, load_config
from shared.raw_loader import load_raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="module1_features.csv")
    args = ap.parse_args()

    config = load_config(args.config)
    print(f"Loading {args.csv} ...", file=sys.stderr)
    df = load_raw(args.csv)
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns.", file=sys.stderr)

    features = build_feature_view(df, config)
    features.to_csv(args.out, index=False)
    print(f"\nWrote {len(features)} rows x {len(features.columns)} columns to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
