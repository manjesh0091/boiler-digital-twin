"""
engine/scoring.py — PAI-S01 BOI composite scoring.

Pure scoring math only: given an actual value and an expected value (the
load-binned historical baseline, computed by baseline.py), this module
derives the per-parameter zone/sub-score and the weighted BOI composite. It
has no pandas/CSV/IO dependency so it stays independently testable;
state_builder.py is responsible for reading module1_features.csv, resolving
each parameter's expected value (and std, for z-score params) from
baseline.get_baseline(), and calling into this module.

Zoning method — two different bases, per parameter:
  - drum_level, furnace_draft, o2: z-score against the load-binned
    baseline's std (|z| <= 1 green, 1-2 amber, >2 red). Chosen over
    %-deviation because these parameters' expected values are small (o2's
    90-100%-load mean is 4.21%, std 0.74) or can swing sign (furnace draft
    is negative), so a fixed %-threshold band is unstable — the same
    absolute swing reads as a wildly different % depending on the load bin.
    o2 was added after live real-data testing showed a genuine, modest
    ~1.4 sigma excursion (real 5.25% vs baseline mean 4.21%) getting
    amplified into a false RED reading purely by the % math — the same
    failure mode already fixed once for drum_level/furnace_draft.
  - the other 7 parameters: %-deviation against fixed amber_pct/red_pct
    thresholds, as before.
If std is missing/non-positive for a z-score parameter (e.g. baseline
lookup failed), classify() falls back to that parameter's amber_pct/red_pct
%-thresholds rather than raising, so a baseline hiccup degrades gracefully
instead of taking scoring down.

Frontend parameter keys -> module1_features.csv columns
---------------------------------------------------------
Confirmed against backend/config/hindalco_boiler9_pai_s01_v2.yaml and the
actual columns present in module1_features.csv.

    steam_pressure   -> MAIN_STEAM_PRESSURE
    steam_temp       -> MAIN_STEAM_TEMPERATURE
    steam_flow       -> MAIN_STEAM_FLOW
    feedwater_flow   -> FEEDWATER_FLOW
    drum_pressure    -> DRUM_PRESSURE
    drum_level       -> DRUM_LEVEL__UNVERIFIED   (needs_verification; candidate
                         tags may be control-valve position feedback rather
                         than a true level signal — plant confirmation pending)
    furnace_draft    -> FURNACE_DRAFT            (available per v2 config —
                         upgraded from synthetic_needed once the proxy tags
                         were confirmed usable)
    o2               -> FLUE_GAS_O2_APH_INLET
    stack_temp       -> STACK_TEMPERATURE        (same raw historian tag as
                         FEGT — known possible spec duplication, see brief)
    fegt             -> FEGT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Zone = Literal["green", "amber", "red"]
DataSource = Literal["real", "unverified", "synthetic", "stale"]


@dataclass(frozen=True)
class ParamSpec:
    key: str
    name: str
    unit: str
    weight: float          # 0.0 = displayed but excluded from BOI weighting
    safety: bool
    amber_pct: float        # |deviation%| <= amber_pct -> green (also the
    red_pct: float          # amber_pct < |deviation%| <= red_pct -> amber, else red
                             # z-score fallback thresholds if std is unavailable)
    use_zscore: bool = False  # True: zone from |z| against baseline std, not %
    z_amber: float = 1.0      # |z| <= z_amber -> green
    z_red: float = 2.0        # z_amber < |z| <= z_red -> amber, else red


# Maps dashboard parameter key -> module1_features.csv column name.
CSV_COLUMN: dict[str, str] = {
    "steam_pressure": "MAIN_STEAM_PRESSURE",
    "steam_temp": "MAIN_STEAM_TEMPERATURE",
    "steam_flow": "MAIN_STEAM_FLOW",
    "feedwater_flow": "FEEDWATER_FLOW",
    "drum_pressure": "DRUM_PRESSURE",
    "drum_level": "DRUM_LEVEL__UNVERIFIED",
    "furnace_draft": "FURNACE_DRAFT",
    "o2": "FLUE_GAS_O2_APH_INLET",
    "stack_temp": "STACK_TEMPERATURE",
    "fegt": "FEGT",
}

# Data-source flag per parameter, per the brief's requirement that
# needs_verification / synthetic_needed tags must never silently pass as
# ground truth. Anything not listed here defaults to "real".
DATA_SOURCE_OVERRIDE: dict[str, DataSource] = {
    "drum_level": "unverified",
}

# Weights: safety-critical params (Drum Level, Furnace Draft) at 0.15,
# others 0.08-0.12, matching the brief. drum_pressure is display-only
# (weight 0) — same convention the old simulator used. Sums to 1.00.
PARAMS: list[ParamSpec] = [
    ParamSpec("steam_pressure", "Main Steam Pressure", "kg/cm²", 0.12, False, amber_pct=3.0, red_pct=7.0),
    ParamSpec("steam_temp", "Main Steam Temperature", "°C", 0.12, False, amber_pct=2.0, red_pct=5.0),
    ParamSpec("steam_flow", "Main Steam Flow", "t/h", 0.10, False, amber_pct=4.0, red_pct=9.0),
    ParamSpec("feedwater_flow", "Feedwater Flow", "t/h", 0.08, False, amber_pct=5.0, red_pct=10.0),
    ParamSpec("drum_pressure", "Drum Pressure", "kg/cm²", 0.00, False, amber_pct=3.0, red_pct=7.0),
    ParamSpec("drum_level", "Drum Level", "mm", 0.15, True, amber_pct=8.0, red_pct=20.0, use_zscore=True),
    ParamSpec("furnace_draft", "Furnace Draft", "mmWC", 0.15, True, amber_pct=10.0, red_pct=25.0, use_zscore=True),
    ParamSpec("o2", "Flue Gas O₂", "% vol", 0.12, False, amber_pct=12.0, red_pct=30.0, use_zscore=True),
    ParamSpec("stack_temp", "Stack Temperature", "°C", 0.08, False, amber_pct=5.0, red_pct=12.0),
    ParamSpec("fegt", "FEGT", "°C", 0.08, False, amber_pct=3.0, red_pct=6.0),
]

PARAM_BY_KEY: dict[str, ParamSpec] = {p.key: p for p in PARAMS}


def deviation_pct(actual: float, expected: float) -> float:
    """Signed deviation%, per the brief's formula. 0 if expected is 0 (avoids div/0)."""
    if expected == 0:
        return 0.0
    return (actual - expected) / expected * 100.0


def _banded_score(dev_abs: float, amber: float, red: float) -> tuple[Zone, float]:
    """Shared 100->80->20->0 decay shape, parameterized by amber/red breakpoints
    (works for both %-deviation units and z-score units)."""
    if dev_abs <= amber:
        score = 100.0 - (dev_abs / amber) * 20.0 if amber else 100.0
        zone: Zone = "green"
    elif dev_abs <= red:
        score = 80.0 - ((dev_abs - amber) / (red - amber)) * 60.0
        zone = "amber"
    else:
        score = max(0.0, 20.0 - ((dev_abs - red) / red) * 20.0)
        zone = "red"
    return zone, score


def classify(param: ParamSpec, actual: float, expected: float, std: float | None = None) -> tuple[Zone, float, float]:
    """Return (zone, signed deviation_pct, sub_score 0..100) for one parameter.

    `deviation_pct` is always computed and returned for display, regardless
    of zoning method — the frontend's Δ% column expects it for every
    parameter. For use_zscore params with a usable std, the returned
    zone/sub_score are instead derived from |z| = |actual-expected|/std; the
    %-based bands are the fallback if std is missing/non-positive.
    """
    dev_pct = deviation_pct(actual, expected)

    if param.use_zscore and std is not None and std > 0:
        z_abs = abs((actual - expected) / std)
        zone, score = _banded_score(z_abs, param.z_amber, param.z_red)
    else:
        dev_abs = abs(dev_pct)
        zone, score = _banded_score(dev_abs, param.amber_pct, param.red_pct)

    # Brief: any single sub-score < 50 forces that parameter's zone to Red,
    # regardless of overall BOI.
    if score < 50.0:
        zone = "red"

    return zone, dev_pct, score


@dataclass
class ParamResult:
    key: str
    name: str
    unit: str
    weight: float
    safety: bool
    value: float
    expected: float
    deviation_pct: float
    zone: Zone
    sub_score: float
    valid: bool
    data_source: DataSource


def score_parameter(
    param: ParamSpec,
    actual: float | None,
    expected: float,
    data_source: DataSource = "real",
    std: float | None = None,
) -> ParamResult:
    """Score a single parameter. actual=None means the row's value is missing/invalid.

    `std` is only used for use_zscore params (drum_level, furnace_draft) —
    pass baseline.get_baseline().std(key, load_pct) for those; harmless to
    omit for the other 8.
    """
    if actual is None:
        return ParamResult(
            param.key, param.name, param.unit, param.weight, param.safety,
            0.0, expected, 0.0, "amber", 0.0, False, data_source,
        )
    zone, dev_pct, score = classify(param, actual, expected, std=std)
    return ParamResult(
        param.key, param.name, param.unit, param.weight, param.safety,
        actual, expected, dev_pct, zone, score, True, data_source,
    )


@dataclass
class BOIResult:
    value: float
    zone: Zone
    suppressed: bool
    data_quality_pct: float
    safety_data_incomplete: bool
    contributions: list[dict] = field(default_factory=list)


def compute_boi(results: list[ParamResult]) -> BOIResult:
    """Weighted-average BOI composite + deviation-waterfall contributions.

    Parameters with weight 0 are display-only and excluded from the weighted
    average. Invalid (missing) parameters are excluded from the average too;
    if an invalid parameter is safety-critical, safety_data_incomplete is set
    so the frontend's incomplete-safety-data banner fires — same behavior as
    the previous simulator.
    """
    total_w = 0.0
    weighted = 0.0
    contributions: list[dict] = []
    any_safety_invalid = False

    for r in results:
        if r.weight == 0:
            continue
        if not r.valid:
            if r.safety:
                any_safety_invalid = True
            continue
        total_w += r.weight
        weighted += r.weight * r.sub_score
        contributions.append({
            "key": r.key,
            "name": r.name,
            "loss": round(r.weight * (100.0 - r.sub_score), 2),
            "weight": r.weight,
            "sub_score": round(r.sub_score, 1),
            "zone": r.zone,
        })

    valid_count = sum(1 for r in results if r.valid)
    dq_pct = (valid_count / len(results) * 100.0) if results else 0.0
    boi = weighted / total_w if total_w > 0 else 0.0
    suppressed = dq_pct < 70.0
    zone: Zone = "green" if boi >= 80 else ("amber" if boi >= 65 else "red")

    contributions.sort(key=lambda c: -c["loss"])
    return BOIResult(
        value=round(boi, 1),
        zone=zone,
        suppressed=suppressed,
        data_quality_pct=round(dq_pct, 1),
        safety_data_incomplete=any_safety_invalid,
        contributions=contributions,
    )
