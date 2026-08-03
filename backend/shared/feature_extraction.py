"""
shared/feature_extraction.py — config-driven raw -> feature-view extraction.

build_feature_view() takes an already-loaded raw dataframe (see
shared/raw_loader.py) plus any tag-mapping config (Module 1's
hindalco_boiler9_pai_s01_v2.yaml, or a cluster config) and returns that
config's filtered/derived view in memory. Extraction logic here is moved
verbatim out of the old loader.py so Module 1 and Cluster code can both
build off one shared raw load instead of each re-reading/re-deriving
independently.
"""
from __future__ import annotations

import sys

import pandas as pd
import yaml


def load_config(path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def build_feature_view(raw_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    out = pd.DataFrame()
    ts_col = config.get("timestamp_column", "Timestamp")
    if ts_col in raw_df.columns:
        out[ts_col] = pd.to_datetime(raw_df[ts_col], errors="coerce")
    else:
        print(f"WARNING: timestamp column '{ts_col}' not found in CSV.", file=sys.stderr)

    availability_report = {}

    for name, spec in config["parameters"].items():
        status = spec.get("status")

        # --- Simple single/average tags -------------------------------------------------
        if status == "available" and "raw_tags" in spec:
            tags = spec["raw_tags"]
            present = [t for t in tags if t in raw_df.columns]
            missing = [t for t in tags if t not in raw_df.columns]
            if missing:
                print(f"NOTE: {name} — expected tag(s) not found in CSV: {missing}", file=sys.stderr)
            if not present:
                availability_report[name] = "NO_MATCHING_COLUMNS"
                continue
            agg = spec.get("aggregation", "single")
            if agg in ("single",) or len(present) == 1:
                out[name] = raw_df[present[0]]
            else:  # average
                out[name] = raw_df[present].mean(axis=1)
            availability_report[name] = "OK"

        # --- Per-stage tags (SH1/SH2/SH3) -------------------------------------------------
        elif status == "available" and spec.get("per_stage"):
            for stage, tags in spec["stages"].items():
                present = [t for t in tags if t in raw_df.columns]
                missing = [t for t in tags if t not in raw_df.columns]
                if missing:
                    print(f"NOTE: {name}_{stage} — tag(s) not found: {missing}", file=sys.stderr)
                col_name = f"{name}_{stage}"
                if present:
                    out[col_name] = raw_df[present].mean(axis=1)
                    availability_report[col_name] = "OK"
                else:
                    availability_report[col_name] = "NO_MATCHING_COLUMNS"

        # --- Header-grouped sum-of-averages (Primary Air Flow) ----------------------------
        elif status == "available" and spec.get("aggregation") == "sum_of_header_averages":
            total = None
            for header, tags in spec["headers"].items():
                present = [t for t in tags if t in raw_df.columns]
                if not present:
                    print(f"NOTE: {name} header {header} — no matching tags found.", file=sys.stderr)
                    continue
                header_avg = raw_df[present].mean(axis=1)
                total = header_avg if total is None else total.add(header_avg, fill_value=0)
            if total is not None:
                out[name] = total
                availability_report[name] = "OK"
            else:
                availability_report[name] = "NO_MATCHING_COLUMNS"

        # --- Needs verification (pull candidate tags but flag clearly) --------------------
        elif status == "needs_verification":
            tags = spec.get("candidate_raw_tags", [])
            present = [t for t in tags if t in raw_df.columns]
            if present:
                out[f"{name}__UNVERIFIED"] = raw_df[present].mean(axis=1)
                availability_report[name] = "PRESENT_BUT_UNVERIFIED"
            else:
                availability_report[name] = "NOT_FOUND"

        # --- Derived (computed after this loop, see below) --------------------------------
        elif status == "derived":
            availability_report[name] = "DERIVED_PENDING"

        # --- Not applicable / synthetic / static: skip in this extraction step ------------
        elif status in ("optional_not_applicable", "synthetic_needed", "static_config"):
            availability_report[name] = status.upper()

        else:
            availability_report[name] = f"UNHANDLED_STATUS({status})"

    # --- Resolve derived parameters now that base columns exist -------------------------
    if "TOTAL_AIR_FLOW" in config["parameters"]:
        parts = config["parameters"]["TOTAL_AIR_FLOW"]["derived_from"]
        if all(p in out.columns for p in parts):
            out["TOTAL_AIR_FLOW"] = out[parts].sum(axis=1)
            availability_report["TOTAL_AIR_FLOW"] = "OK (derived)"
        else:
            availability_report["TOTAL_AIR_FLOW"] = "MISSING_INPUTS_FOR_DERIVATION"

    # OPERATING_MODE is intentionally left to mode_classifier.py (separate module) --
    # this function only assembles the raw feature table it needs.

    print("\n=== FEATURE AVAILABILITY REPORT ===", file=sys.stderr)
    for k, v in availability_report.items():
        print(f"  {k:35s} : {v}", file=sys.stderr)

    return out
