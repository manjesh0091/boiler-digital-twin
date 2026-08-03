"""
engine/mode_classifier.py — PAI-S01 rule-based Operating Mode classifier.

Inputs: MAIN_STEAM_PRESSURE, MAIN_STEAM_TEMPERATURE, BED_TEMP_AVG, UNIT_LOAD
— exactly the four columns listed in OPERATING_MODE.derived_from in the v2
config (MAIN_STEAM_FLOW is deliberately NOT used here, even though the
brief's original SHUTDOWN wording says "pressure/flow" — v2's derived_from
only declares those four, so this stays consistent with the config rather
than silently widening its inputs; flag if flow should be added).

Sampling is 5-minute intervals (module1_features.csv), so a "trailing 10
minute" window is 2 rows.

States: STARTUP, STEADY, LOW_LOAD, SHUTDOWN. No SOOT_BLOWING — this unit has
no soot blower (has_soot_blower: false, v2 config).

Priority when a row could match more than one pattern: SHUTDOWN > STARTUP >
LOW_LOAD > STEADY (default). SHUTDOWN and STARTUP are specific transient
signatures checked first; LOW_LOAD is "steady, but at low load"; STEADY is
the fallback for everything else, including rows where history is too short
(first 2 rows) to compute a slope at all.

Threshold choices below are NOT specified by the brief in numeric form —
each is flagged for plant-engineer review:

  BED_TEMP_STD_THRESHOLD_C = 5.0
      "not yet stable" bed temp, measured as the population std of
      BED_TEMP_AVG over the same trailing 2-row/10-min window as the
      slopes. With only 2 points, std == half the absolute step-to-step
      change, so this threshold effectively fires on a ~10C single-step
      swing in bed temp.

  TEMP_RAMP_RANGE_C = (6.0, 15.0)
      Widens the brief's "~8-10C/10min" to a tolerance band. Real 5-min
      telemetry is noisy — requiring exactly 8.0-10.0 would almost never
      match even during a genuine ramp.

  SHUTDOWN_PRESSURE_SLOPE_PCT = -5.0
      "strongly negative" cutoff for the pressure slope, as %/10min.

  LOW_LOAD_THRESHOLD_PCT = 80.0
      Changed from the brief's original <40% to match baseline.py's own
      [0, 80) bin boundary — deliberate, so "low load" means the same
      thing in both modules. This plant almost never runs below 80% MCR
      (169/91767 real rows per baseline.py's sanity check), so LOW_LOAD
      will be rare against real data regardless of the exact cutoff.

v3 change — absolute-state gates added to SHUTDOWN and STARTUP:
  The v2 rules above only checked *rate of change* (slope), never the
  parameter's actual level. Sanity-checking against the full real dataset
  showed this was a real bug, not just noise: 64 rows got labeled SHUTDOWN
  at pressures of 87-88 kg/cm2 — comfortably inside this plant's normal
  82.6-94.2 kg/cm2 operating band for the entire year — because a brief
  dip within that band still satisfies "-5%/10min." Likewise 168 STARTUP
  hits were at 93-97% load, i.e. ordinary high-load combustion disturbances,
  not cold starts, because the rule never gated on load level.

  SHUTDOWN_PRESSURE_FLOOR_KGCM2 = 60.0
      SHUTDOWN now additionally requires pressure <= 60.0 kg/cm2, well
      below anything this dataset ever shows (real floor is 82.6). This is
      DELIBERATE: this 2024 CSV contains no real shutdown event to
      calibrate against (pressure never once drops out of its normal
      band), so the honest, correct behavior is for SHUTDOWN to fire ~0
      times on this data — not to loosen the floor until it finds
      something to call a shutdown. A rule that fires 64 times on a
      dataset with no shutdowns in it is the bug; a rule that fires 0
      times on the same dataset is doing its job. Needs plant-engineer
      confirmation once real shutdown telemetry exists — see
      MODE_VALIDATION_NOTES below, which state_builder.py surfaces into
      the /state response so a future zero-SHUTDOWN-all-year reading
      isn't mistaken for a broken classifier.

  STARTUP_LOAD_CEILING_PCT = 50.0
      STARTUP now additionally requires load <= 50.0%, so it no longer
      fires on mid-90s%-load disturbances that merely share a startup-like
      slope signature.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

Mode = Literal["STARTUP", "STEADY", "LOW_LOAD", "SHUTDOWN"]

WINDOW_ROWS = 2  # trailing 10 min at 5-min sampling

BED_TEMP_STD_THRESHOLD_C = 5.0        # FLAG FOR REVIEW
TEMP_RAMP_RANGE_C = (6.0, 15.0)       # FLAG FOR REVIEW
SHUTDOWN_PRESSURE_SLOPE_PCT = -5.0    # FLAG FOR REVIEW
LOW_LOAD_THRESHOLD_PCT = 80.0         # aligned with baseline.py's bin boundary
SHUTDOWN_PRESSURE_FLOOR_KGCM2 = 60.0  # FLAG FOR REVIEW — unvalidated, see docstring
STARTUP_LOAD_CEILING_PCT = 50.0       # FLAG FOR REVIEW

REQUIRED_COLUMNS = ["MAIN_STEAM_PRESSURE", "MAIN_STEAM_TEMPERATURE", "BED_TEMP_AVG", "UNIT_LOAD"]

# Per-mode caveats intended to ride along in the /state response (wired in by
# state_builder.py) so a reviewer looking at e.g. zero SHUTDOWN rows all year
# sees *why*, instead of mistaking real, honest behavior for a broken rule.
MODE_VALIDATION_NOTES: dict[Mode, str] = {
    "SHUTDOWN": (
        "Threshold (pressure <= 60.0 kg/cm2 AND strongly negative 10-min slope) "
        "is unvalidated against a real shutdown event -- this dataset never shows "
        "the plant shutting down (pressure stays within 82.6-94.2 kg/cm2 all year). "
        "Firing ~0 times on 2024 data is expected and correct, not a bug. Needs "
        "plant-engineer confirmation once real shutdown telemetry is available."
    ),
}


def compute_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Adds the rolling slope/std columns classify_row() needs.

    Expects df sorted by Timestamp ascending, containing REQUIRED_COLUMNS
    (i.e. module1_features.csv as loaded). Returns a copy — does not mutate
    the input.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"mode_classifier requires columns {missing} not present in df")

    out = df.copy()
    pressure = out["MAIN_STEAM_PRESSURE"]
    temp = out["MAIN_STEAM_TEMPERATURE"]
    bed = out["BED_TEMP_AVG"]

    out["_pressure_slope_10min"] = pressure.diff(WINDOW_ROWS)
    out["_pressure_slope_pct_10min"] = out["_pressure_slope_10min"] / pressure.shift(WINDOW_ROWS) * 100.0
    out["_temp_slope_10min"] = temp.diff(WINDOW_ROWS)
    out["_bed_temp_std_10min"] = bed.rolling(window=WINDOW_ROWS + 1).std(ddof=0)
    return out


def classify_row(row: pd.Series) -> Mode:
    """Classify a single feature-enriched row (see compute_rolling_features) into a Mode."""
    load = row["UNIT_LOAD"]
    pressure = row["MAIN_STEAM_PRESSURE"]
    p_slope = row["_pressure_slope_10min"]
    p_slope_pct = row["_pressure_slope_pct_10min"]
    t_slope = row["_temp_slope_10min"]
    bed_std = row["_bed_temp_std_10min"]

    if pd.isna(p_slope) or pd.isna(t_slope) or pd.isna(bed_std):
        return "STEADY"  # not enough trailing history yet (first 2 rows)

    if (
        p_slope_pct <= SHUTDOWN_PRESSURE_SLOPE_PCT
        and p_slope < 0
        and pressure <= SHUTDOWN_PRESSURE_FLOOR_KGCM2
    ):
        return "SHUTDOWN"

    ramp_lo, ramp_hi = TEMP_RAMP_RANGE_C
    if (
        p_slope > 0
        and ramp_lo <= t_slope <= ramp_hi
        and bed_std > BED_TEMP_STD_THRESHOLD_C
        and load <= STARTUP_LOAD_CEILING_PCT
    ):
        return "STARTUP"

    if load < LOW_LOAD_THRESHOLD_PCT:
        return "LOW_LOAD"

    return "STEADY"


def classify(df: pd.DataFrame) -> pd.Series:
    """Classify every row of a module1_features.csv-shaped DataFrame.

    Returns a Mode Series aligned to df.index.
    """
    enriched = compute_rolling_features(df)
    return enriched.apply(classify_row, axis=1)
