"""
engine/state_builder.py — PAI-S01 real-data /state builder.

Replays module1_features.csv in timestamp order, one row per tick (same
~2s cadence the old simulator used), looping back to the start once it
reaches the end of the year of data. Produces the same /state JSON shape
the frontend already expects (server.py's GET /api/state route) plus a
small number of additive-only fields (data_source per parameter, mode_notes,
scenario_note, source_timestamp) — nothing existing is renamed or removed,
so the frontend needs zero changes.

Ties together:
  - baseline.py        -> expected/std per parameter at the row's real load
  - scoring.py          -> per-parameter zone/sub_score/data_source + BOI
  - mode_classifier.py  -> mode per row, precomputed once for the whole
                           dataset at load time (pure function of history,
                           no need to recompute every tick)

Combustion (PAI-S03) — o2_pct mirrors the real parameters['o2'].value, and
o2_target uses the same baseline.expected('o2', load) as the parameter
grid, since Module 1 integration (see git history). Everything downstream
of O2 (quadrant classification, AFR, CSS, efficiency impact, operator
guidance) was ALREADY substantially real as a result -- those formulas
only ever took o2_value/o2_target/stack_temp_value as inputs, and those
were already real. Phase A (this revision) makes the rest of what's
resolvable real too:

  - co_ppm: STILL SIMULATED, deliberately, not an oversight. The only raw
    tag with "CO" in its name, "CO O/L TO ECO-1" (mapped to Module 1's
    CO_IN_FLUE_GAS), is almost certainly a mislabeled flue-gas PRESSURE
    point, not a CO analyzer reading: its values are negative (-270.7 to
    -15.9 ppm-equivalent, mean -220 -- CO concentration cannot be
    negative) and correlate 0.997 with "FG I/L PR TO ECO-1", a known
    pressure tag, and 0.93 with two other flue-gas-path pressure tags. No
    other CO-ppm candidate tag exists anywhere in the raw historian
    export. Wiring this in as "real" would put fabricated-looking-real
    data under a P1 safety alarm ("UNDER-FIRED ALARM") -- worse than
    leaving it simulated and flagged. Pending plant-engineer confirmation
    of a correct CO analyzer tag (or confirmation none exists on this
    unit). Everything downstream of CO (quadrant's CO-gated branches,
    guidance's CO-gated branches, CSS's S_CO term, Alert Priority Matrix
    P1/P4) is therefore also still simulated/partial -- see the
    "data_source" map on the /state combustion object for the exact
    per-field breakdown.
  - o2_band_low/o2_band_high: NOW REAL (follow-up, same phase -- needed no
    blocking input) -- mean +/- std from engine/baseline.py's existing
    STEADY-trained, load-binned O2 baseline (the SAME one o2's own z-score
    scoring already uses), replacing a hardcoded 5-row rule table inherited
    from the original simulator. The real bands are noticeably tighter
    (e.g. width ~1.0 pct-pt at 90-100% load vs. the old table's flat 3.0)
    and sit at different absolute levels -- the old table was a reasonable
    generic guess, not this plant's actual O2 control tightness. P3's
    "outside band" alert condition inherits this improvement automatically.
  - afr_actual: NOW REAL -- Total Air Flow (TOTAL_AIR_FLOW, already
    derived by Module 1) / Fuel Flow (new: config/hindalco_boiler9_pai_s03_v1.yaml,
    raw tag "FUEL FLOW"), replacing the old formula-off-O2 simulation.
  - afr_design: still simulated (same old formula) -- needs the coal's full
    Ultimate Analysis (Carbon%, Hydrogen%, Oxygen%, Nitrogen%, Sulfur%), not
    yet available. CORRECTED (found during PAI-S02 integration,
    config/hindalco_boiler9_pai_s02_v1.yaml): none of O%/N%/S% are actually
    wired in anywhere in this repo either, despite this comment previously
    claiming otherwise -- grepped config/*.yaml, engine/*.py, shared/*.py
    and found no COAL_O_LAB/COAL_N_LAB/COAL_S_LAB keys or values. Only GCV
    is a real fuel constant. All five ultimate-analysis percentages are
    blocked on the same lab report Punarbasu needs to supply for PAI-S02's
    fuel.* inputs -- one ask unblocks both. Recomputed on the Layer-3
    (per-shift) cadence hook below so swapping in real Ultimate-Analysis-
    based logic in a later phase doesn't require restructuring, even though
    the formula itself hasn't changed yet.
  - efficiency.excess_o2_pct / dry_gas_loss_delta_pct: real (always were,
    incidentally -- pure functions of already-real o2/target/stack_temp).
    efficiency.avoidable_cost_inr_per_hr: still simulated -- needs a real
    coal cost (Rs/tonne); COAL_COST_INR_PER_KG stays a placeholder
    constant.
  - quadrant classification: rule thresholds already exactly matched this
    phase's spec (Q1/Q2/Q3/Q4 bands, CO>500 override) with no code change
    needed -- still gated on simulated CO, so still simulated overall.
  - guidance: still "partial" -- 3 of 5 branches are O2-only (already
    real), 2 are CO-gated (still simulated).
  - css: still "partial" -- S_O2 sub-term real, S_CO and S_Q sub-terms
    simulated (CO-gated). S_AFR term is a Phase-B placeholder (needs
    afr_design, see above).

Interconnection / effective values (PAI-S01 <-> PAI-S02 <-> PAI-S03) —
an interconnection audit found PAI-S02 reading raw tag values independently
of PAI-S01's scoring and PAI-S03's scenario logic: two tabs open at once
could show different O2/feedwater values for "the same" plant reading
during a scenario. Fixed in _tick() by making every tag more than one
module reads go through ONE resolution, in this order:
  1. PAI-S01's own parameter-scoring loop runs first (raw read + Sensor-
     Data-Quality-Drop invalidation + stale-streak detection), producing
     `results` (a list of ParamResult, one per CSV_COLUMN key).
  2. PAI-S03's combustion block resolves the final o2_value/o2_pct_source
     from `results["o2"]` + any active O2-biasing scenario (Under-Air /
     Severe Under-Air).
  3. PAI-S02's efficiency calc runs LAST, consuming the SAME `results`
     entries (steam_flow, steam_pressure, steam_temp, feedwater_flow --
     via `_reused_field()`) and the SAME finalized o2_value/data_source
     PAI-S03 just resolved -- never its own raw row.get(...) call. The two
     PAI-S02-only tags with no PAI-S01 equivalent (FW_PR_TO_FCS,
     FEEDWATER_TEMP_TO_FCS) get their own stale-streak tracker
     (self._s02_stale_runtime + _update_stale(), same rule as step 1) since
     there's no PAI-S01 ParamResult to borrow for those two.
  A None value anywhere in PAI-S02's resolved inputs (e.g. feedwater_flow
  invalidated by Sensor Data Quality Drop) makes efficiency_engine.adapter's
  run_efficiency() return status:"data_gap" instead of computing through a
  gap silently -- matching PAI-S01's own behavior for that same scenario,
  not an independent fallback.
  GCV Check WARN (Dulong/measured HHV factor outside its configured band)
  now fires a real, ack-able "EFFICIENCY"-kind alert via the same
  _fire_or_update_alert()/_mark_below_threshold()/auto-clear mechanism
  every other alert kind uses, not just a badge on the dashboard card.

Calculation cadence (3-layer model, PAI-S03 Dashboard_Method spec):
  - Layer 1 (every tick, ~2s replay cadence): O2, CO, quadrant, alert
    evaluation -- no separate throttle, this is just the tick loop.
  - Layer 2 (every LAYER2_INTERVAL_SECONDS = 5 real minutes): css and
    efficiency are recomputed only on this cadence and held steady
    in between, via self._layer2_cache + self._layer2_last_mono --
    matches the spec and avoids visible flicker on these two composite
    scores.
  - Layer 3 (every LAYER3_INTERVAL_SECONDS = 8h shift): afr_design
    recompute hook, via self._afr_design_cache + self._layer3_last_mono.
    Formula unchanged for now (see afr_design above) -- only the CADENCE
    is new, so Phase B can drop in real Ultimate-Analysis logic without
    restructuring.

Alert Priority Matrix (replaces the old single co_ppm>500 "co::critical"
alert with 5 priorities; see P1_*/P2_*/P3_*/P4_* constants above and
_evaluate_combustion_alerts()):
  - P1 (red, immediate): O2 < 2.0% AND CO > 500 ppm.
  - P2 (red, action): O2 > target + 2.5 percentage points, sustained
    >= 10 min. O2-only -- real.
  - P3 (amber): O2 outside its normal band, sustained >= 5 min. O2-only
    -- real.
  - P4 (amber): CO > 300 ppm, sustained >= 3 min. CO-gated -- simulated.
  - P5 (info): soot blowing / mill change -> mode-only, no alert. This
    unit has no soot blower (has_soot_blower: false, v2 config) and is a
    CFBC design (no pulverizer mills), so P5 has no real trigger
    condition here -- the hook exists but is structurally inert on this
    plant, which is expected, not a bug.
  Combustion alerts (kind="COMBUSTION") get a NEW behavior Module 1's
  existing alerts don't have: a 30-minute ack-snooze
  (COMBUSTION_ACK_SNOOZE_SECONDS) -- an acknowledged combustion alert goes
  quiet, then automatically re-arms (acknowledged reset to False) if it's
  still active 30 minutes later. Module 1's param/safety/composite/CLUSTER
  alerts are UNCHANGED -- they still ack permanently until the underlying
  condition clears, no snooze.

Scenario injection — also flagged rather than silently dropped. The old
SCENARIOS list biased whatever was simulated; now that parameters/BOI/
alerts are real replayed data, most scenarios can't coherently "inject"
anything into them:
  - Excess Air Event / Under-Air-CO Risk Event: still apply, to the
    (simulated) CO/O2-deviation combustion subsystem, same as before.
  - Sensor Data Quality Drop: still applies — marks stack_temp, fegt,
    feedwater_flow invalid while active. Doesn't require faking a value,
    just suppressing validity, so it stays coherent against real data.
  - Drum Level Excursion: NO-OP against real data — drum_level is now a
    real (if unverified) historian reading; synthetically biasing it would
    misrepresent actual plant history. Kept in SCENARIOS for dropdown/API
    compatibility; SCENARIO_NOTES explains the no-op via the API.
  - Soot Blowing Period: NO-OP — this unit has no soot blower
    (has_soot_blower: false, v2 config), so the scenario is inapplicable
    to this plant regardless of data source. Also kept for compatibility.
  - The old simulator's "Normal Operation auto-injects random deviation
    events" behavior is also dropped: it doesn't make sense to have real
    replayed data randomly pretend to be a different scenario. Only a
    scenario the operator explicitly selects has any effect now.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

import pandas as pd

from clusters.cluster_baseline import get_cluster1_baseline
from clusters.cluster_features import build_cluster_view
from clusters.cluster_validator import validate_row as validate_cluster_row
from efficiency_engine.adapter import (
    GCV_CHECK_LOWER, GCV_CHECK_UPPER, FUEL_HHV_KCAL_KG, ETA_DESIGN_PCT,
    run_efficiency, classify_co_flag,
)
from engine.baseline import TRAIN_FRAC, get_baseline
from engine.mode_classifier import MODE_VALIDATION_NOTES
from engine.mode_classifier import classify as classify_modes
from engine.scoring import (
    CSV_COLUMN,
    DATA_SOURCE_OVERRIDE,
    PARAM_BY_KEY,
    ParamResult,
    compute_boi,
    score_parameter,
)
from shared.chronological_split import chronological_split
from shared.data_quality import STALE_STREAK_ROWS, TRAINING_STALE_STREAK_ROWS
from shared.feature_extraction import build_feature_view, load_config
from shared.raw_loader import load_raw

DATA_PATH = Path(__file__).parent.parent / "data" / "processed" / "module1_features.csv"
CLUSTER_CONFIG_PATH = Path(__file__).parent.parent / "clusters" / "cluster_config.yaml"
S03_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hindalco_boiler9_pai_s03_v1.yaml"
S02_CONFIG_PATH = Path(__file__).parent.parent / "config" / "hindalco_boiler9_pai_s02_v1.yaml"

# Relationship metadata for the /state "cross_validation" field and CLUSTER
# alerts -- display name + human-readable member list, keyed by the same
# relationship keys clusters/cluster_validator.py's validate_row() returns.
CLUSTER_RELATIONSHIP_META: dict[str, dict[str, Any]] = {
    "steam_flow_ab_balance": {"name": "Steam Flow A/B Balance", "members": ["Steam Flow-A", "Steam Flow-B"]},
    "water_steam_balance": {"name": "Water-Steam Balance", "members": ["Feedwater Flow", "Total Main Steam Flow"]},
    "air_vs_load_envelope": {"name": "Total Combustion Air vs. Load", "members": ["Total PA Flow", "Total SA Flow", "Total TA Flow", "Load"]},
    "sa_ab_balance": {"name": "Secondary Air A/B Balance", "members": ["SA Flow-A", "SA Flow-B"]},
    "ta_ab_balance": {"name": "Tertiary Air A/B Balance", "members": ["TA Flow-A", "TA Flow-B"]},
}

TICK_SECONDS = 2.0
AUTO_CLEAR_SECONDS = 30.0
HISTORY_LEN = 60
MCR_MW = 150.0  # rated maximum continuous load in MW -- same constant the old simulator used

SCENARIOS = [
    "Normal Operation",
    "Excess Air Event",
    "Under-Air / CO Risk Event",
    "Severe Under-Air / CO Critical Event",
    "Drum Level Excursion",
    "Soot Blowing Period",
    "Sensor Data Quality Drop",
]

SCENARIO_NOTES: dict[str, str | None] = {
    "Normal Operation": None,
    "Excess Air Event": None,
    "Under-Air / CO Risk Event": (
        "Biases combustion.o2_pct down (O2_UNDER_AIR_SCENARIO_BIAS_PCT) in "
        "addition to the existing CO boost, so this scenario exercises both "
        "halves of its own name -- LOW O2 + elevated CO, not CO alone. "
        "Applies ONLY to the combustion view (o2_pct here will diverge from "
        "the real parameters['o2'].value shown on the Parameter Grid while "
        "this scenario is active) -- flagged via data_source.o2_pct "
        "switching to 'simulated' for the duration, same as every other "
        "scenario-injected value in this module."
    ),
    "Severe Under-Air / CO Critical Event": (
        "Distinct from 'Under-Air / CO Risk Event' -- that scenario is "
        "deliberately capped to land CO in (300,500] (see "
        "UNDER_AIR_SCENARIO_CO_TERM_CAP's comment), which means it can "
        "never reach P1 (O2 < 2.0% AND CO > 500 ppm), the single most "
        "severe entry in the Alert Priority Matrix. This scenario exists "
        "specifically to make P1 reachable/demonstrable: O2 is clamped to "
        "<= SEVERE_UNDER_AIR_O2_CAP_PCT and CO is driven to "
        "~SEVERE_UNDER_AIR_CO_TARGET_PPM, both deterministically (not just "
        "biased), so P1 fires reliably rather than depending on real data "
        "coincidence (real O2 < 2.0% happens in only 0.034% of this "
        "dataset's rows). Same o2_pct/excess_air_pct 'simulated' flagging "
        "as the milder scenario applies here too."
    ),
    "Drum Level Excursion": (
        "No effect against real replayed data: drum_level is now a real "
        "(needs_verification) historian reading, not a simulated value -- "
        "injecting a synthetic excursion would misrepresent actual plant "
        "history. Kept in the scenario list for dropdown/API compatibility."
    ),
    "Soot Blowing Period": (
        "No effect: this unit has no soot blower (has_soot_blower: false, "
        "v2 config). Kept in the scenario list for dropdown/API compatibility."
    ),
    "Sensor Data Quality Drop": None,
}

SENSOR_DROP_KEYS = {"stack_temp", "fegt", "feedwater_flow"}

# Generic stale-value detector, applicable to any of the 10 parameters (not
# just fegt/stack_temp -- this is a separate, general safeguard, not a fix
# specific to the known FEGT/STACK_TEMPERATURE tag-duplication issue, which
# stays flagged as-is). A parameter frozen at the exact same raw value for
# more than STALE_STREAK_ROWS consecutive rows (3 rows = 15 min at 5-min
# sampling) is marked data_source: "stale" for as long as it stays frozen --
# same treatment pattern as unverified/synthetic (visible, still scored, but
# not asserted as a trustworthy live reading) -- and is excluded from the
# alert feed while stale, so a frozen sensor can't spam amber/red alerts.
# STALE_STREAK_ROWS now lives in shared/data_quality.py (imported above) so
# baseline training-data filtering (engine/baseline.py, clusters/
# cluster_baseline.py) uses the exact same threshold as this live detector,
# not a second definition that could drift.


def _update_stale(
    rt: "ParamRuntimeState", actual: float | None, threshold: int = STALE_STREAK_ROWS
) -> bool:
    """Same streak-based frozen-value rule as the per-parameter loop below,
    factored out so PAI-S02's own tags (FW_PR_TO_FCS, FEEDWATER_TEMP_TO_FCS
    -- no PAI-S01 ParamResult exists for either) get the identical safety
    net PAI-S01's parameters already have, not a second implementation that
    could drift. `rt` just needs `.last_raw`/`.stale_streak` -- any
    ParamRuntimeState instance works, including ones outside
    self._param_runtime.

    `threshold` defaults to the live STALE_STREAK_ROWS (3) rule every
    PAI-S01 parameter and the two PAI-S02-only tags above use. PAI-S02's
    Gate 3 (Stack Temp) passes TRAINING_STALE_STREAK_ROWS (12) instead --
    STACK_TEMPERATURE's whole-degree quantization trips the 3-row rule on
    ordinary slow drift, not genuine freezing (same reasoning as Cluster 1's
    training-exclusion threshold). Scoped to that one call site only --
    Module 1's own live parameter-grid alerting for stack_temp still uses
    the 3-row default via the main scoring loop below."""
    if actual is not None and rt.last_raw is not None and actual == rt.last_raw:
        rt.stale_streak += 1
    else:
        rt.stale_streak = 0
    rt.last_raw = actual
    return rt.stale_streak >= threshold


# ---- Phase D: Daily/Shift Summary Table -- fixed 8-hour blocks over the
# REPLAYED row's own source_ts, not wall-clock. Our data is a historical
# replay (not genuinely live shifts), so this is a reasonable fixed time
# window over the replay for this phase, not a real plant shift schedule --
# a documented simplification, per the brief. ----
SHIFT_HOURS = 8


def _shift_key(ts: datetime) -> tuple[str, str]:
    shift_no = ts.hour // SHIFT_HOURS + 1
    date_str = ts.date().isoformat()
    label = f"{date_str} Shift {shift_no} ({(shift_no - 1) * SHIFT_HOURS:02d}-{shift_no * SHIFT_HOURS:02d}h)"
    return f"{date_str}_S{shift_no}", label


AMBIENT_TEMP = 30.0
GCV = 3610.0  # real plant value (config/hindalco_boiler9_pai_s01_v2.yaml: COAL_GCV static_config,
              # proximate-analysis basis) -- was an arbitrary 4000.0 placeholder before this fix
COAL_COST_INR_PER_KG = 6.5  # still a placeholder -- no real coal-cost input yet, see module docstring
STEAM_TO_COAL = 6.5

# ---- PAI-S03 combustion: calculation cadence (3-layer model per the
# PAI-S03 Dashboard_Method spec) ----
# Layer 1 (O2, CO, quadrant, alert evaluation) runs every tick -- no
# separate constant needed, it's just "the tick loop."
LAYER2_INTERVAL_SECONDS = 300.0     # 5 real minutes: CSS, DGL efficiency
LAYER3_INTERVAL_SECONDS = 8 * 3600.0  # 8-hour shift: AFR/theoretical-air design recompute

# ---- PAI-S03 combustion: Alert Priority Matrix thresholds ----
# P2/P3/P4 require the condition to hold continuously for a minimum
# duration before firing (not an instant blip) -- tracked the same way
# below_threshold_since already tracks "how long has this been quiet."
P1_O2_PCT_MAX = 2.0          # O2 < this AND CO > P1_CO_PPM_MIN -> immediate
P1_CO_PPM_MIN = 500.0
P2_O2_DEV_PCT_ABOVE = 2.5    # O2 > target + this, sustained...
P2_SUSTAINED_SECONDS = 600.0  # ...for >= 10 min
P3_SUSTAINED_SECONDS = 300.0  # O2 outside its normal band for >= 5 min
P4_CO_PPM_MIN = 300.0        # CO > this, sustained...
P4_SUSTAINED_SECONDS = 180.0  # ...for >= 3 min
COMBUSTION_ACK_SNOOZE_SECONDS = 1800.0  # 30 min -- combustion alerts only

# "Under-Air / CO Risk Event" scenario: O2 bias. Correctness fix, not just a
# demo convenience -- the scenario's own NAME promises both an under-air
# (low O2) condition and elevated CO, but until this constant existed it
# only ever did the CO half (base_co += 350.0 below). Fixed magnitude, same
# pattern as that existing CO bias (a flat constant, not extra randomness)
# -- applied only to combustion's own o2_value (see _tick()), never to
# Module 1's parameters['o2'].value (the Parameter Grid), which must stay
# real/unbiased regardless of which combustion scenario is selected.
O2_UNDER_AIR_SCENARIO_BIAS_PCT = -1.2

# Same scenario, CO side. The general o2_dev-linked CO escalation term
# (base_co += (abs(o2_dev)**2.2)*180, see _tick() below -- pre-existing,
# used by every tick regardless of scenario) is steep enough that combining
# it uncapped with this scenario's own CO boost overshoots CO_CRITICAL
# (>500ppm) far more often than it lands in the "elevated, not yet
# critical" (300,500] window the LOW-O2+CO guidance branch needs to be
# reachable at all. Verified empirically against the full real O2
# distribution: the original flat +350 (uncapped term) landed in (300,500]
# only ~20-37% of the time depending on tuning, vs. ~32-77% overshooting
# straight to CO_CRITICAL -- never a clean majority either way. Capping the
# term's contribution + a recalibrated flat boost, SCOPED ONLY to this one
# scenario (every other scenario and Normal Operation keep the term
# uncapped, see _tick()), reliably centers CO in the intended window across
# the ENTIRE real O2 distribution: 100% in-window, 0% quiet, 0% overshoot.
UNDER_AIR_SCENARIO_CO_TERM_CAP = 120.0
UNDER_AIR_SCENARIO_CO_FLAT_BOOST = 250.0

# "Severe Under-Air / CO Critical Event" -- a DISTINCT, more extreme
# scenario whose entire purpose is making P1 (O2 < P1_O2_PCT_MAX AND
# CO > P1_CO_PPM_MIN, the single most severe alert in the matrix) reliably
# reachable, since the milder scenario above is deliberately capped away
# from ever reaching it. Both O2 and CO are driven DETERMINISTICALLY here
# (a hard cap / fixed target + small noise), not just biased like the
# milder scenario -- P1 being untestable is worse than this one being
# slightly less "naturalistic," so reliability was prioritized over subtlety.
SEVERE_UNDER_AIR_O2_CAP_PCT = 1.7      # o2_value = min(this, real_o2 + bias) -- comfortably under P1_O2_PCT_MAX (2.0)
SEVERE_UNDER_AIR_O2_BIAS_PCT = -2.5
SEVERE_UNDER_AIR_CO_TARGET_PPM = 620.0  # base_co = this +/- noise -- comfortably over P1_CO_PPM_MIN (500)
SEVERE_UNDER_AIR_CO_NOISE_PPM = 20.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Cluster 1 cross-validation helpers ----

def _cluster_note(rel_key: str, status: str, detail: dict[str, Any]) -> str:
    """Human-readable one-line summary of a cluster_validator RelationshipResult,
    for the /state "cross_validation" field and CLUSTER alert messages."""
    if status == "unknown":
        return "Insufficient data (sensor gap or invalid reading)."

    if rel_key == "steam_flow_ab_balance":
        ab = detail.get("ab_diff_pct")
        if status == "consistent":
            return f"A/B agree within tolerance (Δ {ab:.1f}%)."
        if status == "outlier":
            return (
                f"Steam Flow-{detail['flagged_side']} flagged, Steam Flow-"
                f"{detail['trusted_side']} trusted (Δ {ab:.1f}%, correlated "
                "against Feedwater Flow)."
            )
        return f"A/B disagree (Δ {ab:.1f}%) but neither side is clearly closer to Feedwater Flow."

    if rel_key == "water_steam_balance":
        dev = detail.get("deviation_pct")
        if status == "consistent":
            return f"Balance deviation {dev:+.1f}% within normal band."
        if status == "outlier":
            return (
                f"Balance deviation {dev:+.1f}% outside normal band; "
                f"{detail['flagged_for_correction'].replace('_', ' ')} flagged "
                "(correlated against Load)."
            )
        return f"Balance deviation {dev:+.1f}% outside normal band; neither side is clearly closer to Load's expectation."

    if rel_key == "air_vs_load_envelope":
        val = detail.get("total_combustion_air")
        mean = detail.get("baseline_mean")
        if status == "consistent":
            return f"Total Combustion Air {val:.1f} TPH within expected envelope (baseline {mean:.1f} TPH)."
        return f"Total Combustion Air {val:.1f} TPH outside expected envelope (baseline {mean:.1f} TPH)."

    if rel_key in ("sa_ab_balance", "ta_ab_balance"):
        side = detail.get("side_dev_pct")
        mean = detail.get("baseline_mean_pct")
        if status == "consistent":
            return f"Side deviation {side:.1f}% within normal band (baseline {mean:.1f}%)."
        return f"Side deviation {side:.1f}% outside normal band (baseline {mean:.1f}%)."

    return status


# ---- combustion helpers: unchanged from the old simulator (simulation.py) ----
# NOTE: the old hardcoded _o2_band(load_frac) rule table that used to live
# here is GONE -- o2_band_low/high are now real (see _tick(): computed as
# self._baseline.stats_for('o2', load_pct).mean +/- std, the exact same
# STEADY-trained, load-binned baseline engine/baseline.py already fits for
# o2's own z-score scoring elsewhere in this same tick). No blocking input
# was needed for this one -- Module 1's baseline already covers 'o2'.

def _excess_air(o2: float) -> float:
    denom = 21.0 - o2
    if denom <= 0.01:
        return 999.9
    return o2 / denom * 100.0


def _afr(o2: float) -> float:
    return 7.5 * (1.0 + _excess_air(o2) / 100.0)


def _css(o2: float, target: float, co: float, quadrant: dict[str, Any]) -> float:
    dev = abs(o2 - target)
    s_o2 = max(0.0, 100.0 - dev * 25.0)
    s_co = max(0.0, 100.0 - (co / 6.0))
    s_q = {"Q1": 100, "Q0": 70, "Q3": 60, "Q2": 20, "Q4": 20, "CO_CRITICAL": 0}[quadrant["id"]]
    return 0.5 * s_o2 + 0.3 * s_co + 0.2 * s_q


def _efficiency_impact(o2: float, target: float, stack_temp: float, load_mw: float) -> dict[str, Any]:
    excess = max(0.0, o2 - target)
    dgl_delta = 0.028 * excess * max(0.0, stack_temp - AMBIENT_TEMP) / (GCV / 1000.0)
    steam_tph = load_mw * 2.0
    coal_kg_hr = steam_tph * 1000.0 / STEAM_TO_COAL
    avoidable_heat_kcal_hr = coal_kg_hr * (dgl_delta / 100.0) * GCV  # real -- feeds guidance's "B kCal/hr" (see below)
    avoidable_cost = coal_kg_hr * (dgl_delta / 100.0) * COAL_COST_INR_PER_KG  # simulated -- placeholder coal cost
    return {
        "excess_o2_pct": round(excess, 2),
        "dry_gas_loss_delta_pct": round(dgl_delta, 3),
        "avoidable_heat_kcal_hr": round(avoidable_heat_kcal_hr, 0),
        "avoidable_cost_inr_per_hr": round(avoidable_cost, 0),
    }


# Operator guidance templates -- verbatim from the PAI-S03 Dashboard_Method
# spec sheet (HIGH O2 / LOW O2 advisories), swapped in to replace this
# project's own earlier wording for those two specific branches. The other
# three branches (CO-only critical, mild under-air warning, in-band OK)
# have no spec-provided template and keep their original wording.
#
# Per-value provenance within each template (the message TEXT is verbatim;
# this comment is where the real/simulated distinction actually lives,
# since these two templates mix both within one sentence):
#   HIGH O2: X (O2), Y (target), Z (excess air %) -- all REAL. A (FD damper
#     reduction %) is a DERIVED ESTIMATE, not a calibrated damper-position
#     curve (none exists in this data) -- approximated as the excess-air
#     percentage-point delta between current and target O2, which is the
#     standard first-order proxy; still built entirely from real O2/target,
#     so treated as real-but-approximate. B (kCal/hr) is real (real
#     o2/target/stack_temp/load, plus the plant's actual confirmed GCV
#     static config, not a placeholder). C (Rs/hr) is SIMULATED --
#     COAL_COST_INR_PER_KG is still a placeholder pending a real coal-cost
#     input (Phase B).
#   LOW O2: X (O2), Y (target) are REAL. D (CO reading) is SIMULATED --
#     same CO_IN_FLUE_GAS tag-mislabeling issue as everywhere else CO
#     appears in this module (see module docstring); this line's CO number
#     inherits that flag even though the O2 portion of the same message is
#     real.
def _operator_guidance(o2: float, target: float, co: float, efficiency: dict[str, Any]) -> dict[str, Any]:
    """Returns {"level", "text", "references_co"}. references_co is True
    only for the two branches that display/depend on an actual CO ppm
    VALUE (both currently simulated, see module docstring) -- NOT for the
    mild under-air branch below, which just says "monitor CO closely" as a
    generic instruction without citing a CO number. The frontend uses this
    flag to show a caveat exactly when it's warranted, instead of either
    string-matching the message text (fragile) or flagging every guidance
    message regardless of which branch is active (cries wolf on the 3
    branches that are already fully real).
    """
    if co > 500:
        return {"level": "critical", "text": f"CO at {co:.0f} ppm — verify air supply, do NOT reduce further until CO confirmed safe.", "references_co": True}
    if o2 < target - 1.0 and co > 300:
        # LOW O2 advisory (verbatim) -- O2/target real, CO reading simulated (see docstring above).
        return {
            "level": "critical",
            "text": (
                f"O2 at {o2:.1f}% (target {target:.1f}%). CO reading at {co:.0f} ppm. "
                "Verify FD/PA air supply. Do NOT reduce further until CO confirmed safe."
            ),
            "references_co": True,
        }
    if o2 > target + 2.0:
        # HIGH O2 advisory (verbatim, both lines) -- O2/target/excess-air/kCal
        # real, FD-damper-% a real-but-approximate proxy, Rs/hr simulated
        # (see docstring above).
        excess_air_pct = _excess_air(o2)
        damper_reduction_pct = max(0.0, excess_air_pct - _excess_air(target))
        heat_kcal_hr = efficiency.get("avoidable_heat_kcal_hr", 0.0)
        cost_inr_hr = efficiency.get("avoidable_cost_inr_per_hr", 0.0)
        return {
            "level": "warning",
            "text": (
                f"O2 at {o2:.1f}% (target {target:.1f}%). Excess air at {excess_air_pct:.1f}%. "
                f"Consider reducing FD damper position by {damper_reduction_pct:.1f}%. "
                f"Estimated saving: {heat_kcal_hr:.0f} kCal/hr = ₹{cost_inr_hr:.0f}/hr at current coal cost."
            ),
            "references_co": False,
        }
    if o2 < target - 0.5:
        return {"level": "warning", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%). Trending under-air — monitor CO closely.", "references_co": False}
    return {"level": "ok", "text": f"O₂ at {o2:.1f}% within target band ({target:.1f}%). Combustion trim optimal.", "references_co": False}


@dataclass
class ParamRuntimeState:
    """Rolling (session-since-start) history + day min/max/avg for one parameter."""
    key: str
    history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    day_min: float = math.inf
    day_max: float = -math.inf
    day_sum: float = 0.0
    day_count: int = 0
    last_raw: float | None = None   # for the stale-value detector
    stale_streak: int = 0           # consecutive rows equal to last_raw


@dataclass
class Alert:
    id: str
    parameter_key: str
    parameter_name: str
    severity: str          # "amber" | "red"
    kind: str              # "param" | "composite" | "safety" | "co" | "CLUSTER" | "COMBUSTION"
    message: str
    first_ts: str
    last_update_ts: str
    active: bool = True
    acknowledged: bool = False
    cleared_ts: str | None = None
    below_threshold_since: float | None = None  # monotonic seconds
    priority: str | None = None       # "P1".."P5" -- COMBUSTION alerts only, else None
    acknowledged_mono: float | None = None  # monotonic ack time -- COMBUSTION ack-snooze only


class RealDataStateBuilder:
    """Replays the 80% TEST-WINDOW portion of module1_features.csv (and,
    row-aligned, Cluster 1's feature view) and produces /state snapshots
    from it.

    Data philosophy (see engine/baseline.py, clusters/cluster_baseline.py):
    the first 20% of each calendar month trains the baselines and is never
    shown as live data; the remaining ~80% is genuinely unseen data that
    gets replayed here, in timestamp order, as the "live" stream. Both
    Module 1's baseline (engine/baseline.py) and Cluster 1's baseline
    (clusters/cluster_baseline.py) already exclude the training window from
    what they were FIT on -- this class additionally makes sure the LIVE
    REPLAY itself never shows a training-window row, so the dashboard never
    presents historical-training data as if it were current.

    Row alignment: module1_features.csv and Cluster 1's feature view (built
    from the same raw CSV, see shared/raw_loader.py) share the identical
    set and order of timestamps for the full dataset (verified in Phase A).
    Splitting each independently with the same chronological_split() call
    and the same TRAIN_FRAC therefore yields identical test-window
    timestamp sequences -- checked with an assertion at startup rather than
    assumed silently.
    """

    def __init__(self, csv_path: Path = DATA_PATH):
        df = pd.read_csv(csv_path, parse_dates=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        _train_df, test_df, split_info = chronological_split(df, "Timestamp", TRAIN_FRAC)
        self._df = test_df
        self._split_info = split_info
        self._n_rows = len(self._df)
        self._row_idx = 0
        self._modes = classify_modes(self._df)  # precomputed once -- pure function of history
        self._baseline = get_baseline()

        # Cluster 1: same test-window split, applied to Cluster 1's own
        # feature view (built from the raw CSV, not module1_features.csv --
        # Cluster 1 needs Steam Flow-A/B, SA/TA-A/B kept separate, which
        # Module 1's config averages/sums away). The baseline itself was
        # already fit on the training window only (clusters/cluster_baseline.py);
        # get_cluster1_baseline() reuses that trained singleton rather than
        # retraining here.
        self._cluster_config = load_config(CLUSTER_CONFIG_PATH)
        raw_df = load_raw()
        cluster_view_full = build_cluster_view(raw_df, self._cluster_config).sort_values("Timestamp").reset_index(drop=True)
        _c_train, cluster_test_view, _c_split_info = chronological_split(cluster_view_full, "Timestamp", TRAIN_FRAC)
        self._cluster_view = cluster_test_view
        self._cluster_baseline = get_cluster1_baseline()

        if len(self._cluster_view) != self._n_rows or not (
            self._df["Timestamp"].reset_index(drop=True) == self._cluster_view["Timestamp"].reset_index(drop=True)
        ).all():
            raise RuntimeError(
                "Module 1 and Cluster 1 replay windows are misaligned -- "
                "expected identical timestamp sequences from independently "
                "splitting module1_features.csv and Cluster 1's feature view."
            )

        # PAI-S03 (combustion): same test-window split again, applied to the
        # one additional tag Module 1 doesn't already extract (Fuel Flow) --
        # reuses the SAME raw_df already loaded above, no extra CSV read.
        s03_config = load_config(S03_CONFIG_PATH)
        s03_view_full = build_feature_view(raw_df, s03_config).sort_values("Timestamp").reset_index(drop=True)
        _s03_train, s03_test_view, _s03_split_info = chronological_split(s03_view_full, "Timestamp", TRAIN_FRAC)
        self._s03_view = s03_test_view

        if len(self._s03_view) != self._n_rows or not (
            self._df["Timestamp"].reset_index(drop=True) == self._s03_view["Timestamp"].reset_index(drop=True)
        ).all():
            raise RuntimeError(
                "Module 1 and PAI-S03 replay windows are misaligned -- "
                "expected identical timestamp sequences."
            )

        # PAI-S02 (efficiency): same pattern again, for the one additional
        # tag boiler_duty.FW_PR_TO_FCS needs that Module 1 doesn't already
        # extract -- see config/hindalco_boiler9_pai_s02_v1.yaml.
        s02_config = load_config(S02_CONFIG_PATH)
        s02_view_full = build_feature_view(raw_df, s02_config).sort_values("Timestamp").reset_index(drop=True)
        _s02_train, s02_test_view, _s02_split_info = chronological_split(s02_view_full, "Timestamp", TRAIN_FRAC)
        self._s02_view = s02_test_view

        if len(self._s02_view) != self._n_rows or not (
            self._df["Timestamp"].reset_index(drop=True) == self._s02_view["Timestamp"].reset_index(drop=True)
        ).all():
            raise RuntimeError(
                "Module 1 and PAI-S02 replay windows are misaligned -- "
                "expected identical timestamp sequences."
            )

        self._last_efficiency_snapshot: dict[str, Any] = {}

        self._param_runtime: dict[str, ParamRuntimeState] = {k: ParamRuntimeState(k) for k in CSV_COLUMN}

        # PAI-S02 tags with no PAI-S01 ParamResult equivalent (FW_PR_TO_FCS,
        # FEEDWATER_TEMP_TO_FCS aren't in CSV_COLUMN/PARAM_BY_KEY) get their
        # own minimal stale-streak tracker via the same ParamRuntimeState/
        # _update_stale rule every PAI-S01 parameter already uses -- see
        # efficiency_engine/adapter.py's boiler_duty_fields docstring.
        self._s02_stale_runtime: dict[str, ParamRuntimeState] = {
            "FW_PR_TO_FCS": ParamRuntimeState("FW_PR_TO_FCS"),
            "FEEDWATER_TEMP_TO_FCS": ParamRuntimeState("FEEDWATER_TEMP_TO_FCS"),
        }
        # PAI-S02 Gate 3's own independent Stack Temp staleness tracker --
        # deliberately separate from self._param_runtime["stack_temp"] (which
        # PAI-S01's live parameter grid uses at the 3-row STALE_STREAK_ROWS
        # threshold). Gate 3 reads the same raw STACK_TEMPERATURE tag but
        # judges staleness at the 12-row TRAINING_STALE_STREAK_ROWS
        # threshold instead, so an independent streak counter is required --
        # sharing self._param_runtime["stack_temp"]'s counter would conflate
        # the two thresholds' streaks.
        self._s02_stack_temp_gate_runtime = ParamRuntimeState("stack_temp_gate3")

        # Phase D: Daily/Shift Summary Table accumulator, keyed by
        # _shift_key()'s fixed 8-hour block over the row's own source_ts.
        # Naturally bounded -- the test window loops forever
        # (self._row_idx wraps), so a later loop pass revisits an existing
        # key and just updates its running average, never grows past however
        # many real calendar shifts exist in the test window.
        self._shift_stats: dict[str, dict[str, Any]] = {}
        self._boi_history: Deque[dict[str, float]] = deque(maxlen=HISTORY_LEN)
        self._alerts: dict[str, Alert] = {}

        self._mode: str | None = None
        self._mode_since = _now_iso()
        self._mode_since_mono = time.monotonic()

        self._scenario = "Normal Operation"

        # combustion subsystem's own bit of state -- co_ppm simulated, see module docstring
        self._co_ppm = 80.0
        self._co_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self._quadrant_trail: Deque[dict[str, float]] = deque(maxlen=25)

        # Layer 2 (5-min) cadence cache: css + efficiency held steady between
        # recomputes. Seeded None so the very first tick always computes.
        self._layer2_last_mono: float | None = None
        self._layer2_cache: dict[str, Any] = {"css": 0.0, "efficiency": None}

        # Layer 3 (per-shift) cadence cache: afr_design. Formula unchanged
        # (still simulated) -- only the recompute CADENCE is new, see docstring.
        self._layer3_last_mono: float | None = None
        self._afr_design_cache: float = 0.0

        # Alert Priority Matrix P2/P3/P4 sustained-duration trackers --
        # monotonic timestamp of when each condition FIRST became true,
        # reset to None the instant it's no longer true (mirrors
        # below_threshold_since's pattern, just inverted).
        self._p2_condition_since: float | None = None  # O2 > target+2.5, sustained
        self._p3_condition_since: float | None = None  # O2 outside band, sustained
        self._p4_condition_since: float | None = None  # CO > 300, sustained

        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._last_snapshot: dict[str, Any] = {}

    # ---------- lifecycle ----------
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        try:
            # seed HISTORY_LEN rows immediately so sparklines have shape as
            # soon as the first client hits /state, same as the old simulator.
            for _ in range(HISTORY_LEN):
                self._tick()
            while True:
                await asyncio.sleep(TICK_SECONDS)
                async with self._lock:
                    self._tick()
        except asyncio.CancelledError:
            return

    # ---------- controls ----------
    async def set_scenario(self, scenario: str) -> None:
        async with self._lock:
            self._scenario = scenario if scenario in SCENARIOS else "Normal Operation"

    async def acknowledge(self, alert_id: str) -> bool:
        async with self._lock:
            a = self._alerts.get(alert_id)
            if not a:
                return False
            a.acknowledged = True
            a.acknowledged_mono = time.monotonic()  # only consulted for kind=="COMBUSTION" (ack-snooze)
            return True

    async def acknowledge_all(self) -> int:
        async with self._lock:
            n = 0
            for a in self._alerts.values():
                if a.active and not a.acknowledged:
                    a.acknowledged = True
                    a.acknowledged_mono = time.monotonic()
                    n += 1
            return n

    # ---------- tick ----------
    def _tick(self) -> None:
        now_mono = time.monotonic()
        row = self._df.iloc[self._row_idx]
        cluster_row = self._cluster_view.iloc[self._row_idx]
        fuel_row = self._s03_view.iloc[self._row_idx]
        s02_row = self._s02_view.iloc[self._row_idx]
        row_mode: str = self._modes.iloc[self._row_idx]
        source_ts = row["Timestamp"]

        load_pct = float(row["UNIT_LOAD"])
        load_frac = load_pct / 100.0
        load_mw = load_frac * MCR_MW

        # advance replay position, looping back to the start at year-end
        self._row_idx = (self._row_idx + 1) % self._n_rows

        # ---- mode tracking ----
        if row_mode != self._mode:
            self._mode = row_mode
            self._mode_since = _now_iso()
            self._mode_since_mono = now_mono

        # ---- scenario: only Sensor Data Quality Drop touches real parameters ----
        active_scenario = self._scenario
        sensor_drop_active = active_scenario == "Sensor Data Quality Drop"

        # ---- score each real parameter ----
        results: list[ParamResult] = []
        stale_flags: dict[str, bool] = {}
        for key, column in CSV_COLUMN.items():
            param = PARAM_BY_KEY[key]
            raw_val = row.get(column)
            actual = None if pd.isna(raw_val) else float(raw_val)
            if sensor_drop_active and key in SENSOR_DROP_KEYS:
                actual = None

            rt = self._param_runtime[key]

            # stale-value detector: streak of consecutive rows equal to the
            # previous raw reading, independent of the sensor-drop scenario
            is_stale = _update_stale(rt, actual)
            stale_flags[key] = is_stale

            data_source = "stale" if is_stale else DATA_SOURCE_OVERRIDE.get(key, "real")

            stats = self._baseline.stats_for(key, load_pct)
            std = stats.std if param.use_zscore else None

            result = score_parameter(param, actual, stats.mean, data_source=data_source, std=std)
            results.append(result)

            if actual is not None:
                rt.history.append(round(actual, 3))
                rt.day_min = min(rt.day_min, actual)
                rt.day_max = max(rt.day_max, actual)
                rt.day_sum += actual
                rt.day_count += 1

        boi_result = compute_boi(results)
        self._boi_history.append({"ts": time.time(), "boi": boi_result.value, "load": round(load_frac, 3)})

        # ---- alerts: per-parameter zone transitions ----
        for result in results:
            alert_id = f"param::{result.key}"
            if stale_flags[result.key]:
                # frozen sensor -- visible in the grid (data_source: "stale")
                # but excluded from the alert feed while it stays frozen.
                self._mark_below_threshold(alert_id, now_mono)
                continue
            if not result.valid:
                self._fire_or_update_alert(
                    alert_id, result.key, result.name, "amber", "param",
                    f"{result.name} sensor data invalid", now_mono,
                )
                continue
            if result.zone == "red":
                self._fire_or_update_alert(
                    alert_id, result.key, result.name, "red",
                    "safety" if result.safety else "param",
                    f"{result.name} in RED zone: {result.value:.1f} {result.unit} (exp {result.expected:.1f})",
                    now_mono,
                )
            elif result.zone == "amber":
                self._fire_or_update_alert(
                    alert_id, result.key, result.name, "amber",
                    "safety" if result.safety else "param",
                    f"{result.name} deviation: {result.value:.1f} {result.unit} (exp {result.expected:.1f})",
                    now_mono,
                )
            else:
                self._mark_below_threshold(alert_id, now_mono)

        # composite BOI alert
        if boi_result.zone == "red" and not boi_result.suppressed:
            self._fire_or_update_alert(
                "composite::boi", "boi", "Boiler Operating Index", "red", "composite",
                f"BOI at {boi_result.value:.1f} — multiple parameters degraded", now_mono,
            )
        elif boi_result.zone == "amber" and not boi_result.suppressed:
            self._fire_or_update_alert(
                "composite::boi", "boi", "Boiler Operating Index", "amber", "composite",
                f"BOI at {boi_result.value:.1f} — performance degrading", now_mono,
            )
        else:
            self._mark_below_threshold("composite::boi", now_mono)

        # ---- combustion: simulated CO/quadrant/AFR/CSS/efficiency/guidance,
        # driven by the REAL o2 reading + real load (see module docstring) ----
        o2_result = next(r for r in results if r.key == "o2")
        o2_value = o2_result.value if o2_result.valid else o2_result.expected
        o2_target = o2_result.expected
        # Scenario correctness fix: "Under-Air / CO Risk Event" now biases
        # O2 down too, not just CO (see O2_UNDER_AIR_SCENARIO_BIAS_PCT's own
        # comment for why). Applied here, before o2_dev/quadrant/guidance/
        # alerts are computed, so everything downstream in this tick sees
        # ONE consistent (biased) O2 -- never Module 1's real
        # parameters['o2'].value, which is untouched by any scenario here.
        o2_pct_source = "real"
        if active_scenario == "Under-Air / CO Risk Event":
            o2_value = o2_value + O2_UNDER_AIR_SCENARIO_BIAS_PCT
            o2_pct_source = "simulated"
        elif active_scenario == "Severe Under-Air / CO Critical Event":
            # Deterministic cap, not just a bias -- see this scenario's
            # constants' comment for why P1 needs a reliable trigger.
            o2_value = min(SEVERE_UNDER_AIR_O2_CAP_PCT, o2_value + SEVERE_UNDER_AIR_O2_BIAS_PCT)
            o2_pct_source = "simulated"

        # ---- PAI-S02: boiler efficiency (ASME PTC-4-style indirect/
        # heat-loss method, backend/efficiency_engine/). Interconnection fix:
        # this runs HERE, after PAI-S01's scoring loop and PAI-S03's O2
        # scenario-bias resolution above -- not before them -- so it reads
        # the SAME effective o2_value PAI-S03 is about to use below, and the
        # SAME ParamResult objects (PAI-S01's own stale-detection + Sensor-
        # Data-Quality-Drop invalidation already applied) for every
        # boiler_duty field it shares with PAI-S01. Never an independent raw
        # row read anymore -- see efficiency_engine/adapter.py's module
        # docstring for the full rationale and
        # config/hindalco_boiler9_pai_s02_v1.yaml for why most non-
        # boiler_duty inputs are still synthetic_needed. ----
        def _reused_field(key: str) -> tuple[float | None, str]:
            r = next(x for x in results if x.key == key)
            return (r.value, r.data_source) if r.valid else (None, r.data_source)

        fw_pr_raw = s02_row.get("FW_PR_TO_FCS")
        fw_pr_value = None if pd.isna(fw_pr_raw) else float(fw_pr_raw)
        fw_pr_stale = _update_stale(self._s02_stale_runtime["FW_PR_TO_FCS"], fw_pr_value)
        fw_pr_source = "stale" if fw_pr_stale else "real"

        fw_temp_raw = row.get("FEEDWATER_TEMP_TO_FCS")
        fw_temp_value = None if pd.isna(fw_temp_raw) else float(fw_temp_raw)
        fw_temp_stale = _update_stale(self._s02_stale_runtime["FEEDWATER_TEMP_TO_FCS"], fw_temp_value)
        fw_temp_source = "stale" if fw_temp_stale else "real"

        boiler_duty_fields = {
            "MAIN_STEAM_FLOW": _reused_field("steam_flow"),
            "MAIN_STEAM_PRESSURE": _reused_field("steam_pressure"),
            "MAIN_STEAM_TEMPERATURE": _reused_field("steam_temp"),
            "FEEDWATER_FLOW": _reused_field("feedwater_flow"),
            "FW_PR_TO_FCS": (fw_pr_value, fw_pr_source),
            "FEEDWATER_TEMP_TO_FCS": (fw_temp_value, fw_temp_source),
        }
        # O2 for PAI-S02 = the exact value PAI-S03 resolved just above --
        # "stale" if the underlying tag is frozen (independent of any
        # scenario, takes priority), else whatever o2_pct_source already
        # says (real / simulated-under-scenario).
        o2_efficiency_source = "stale" if o2_result.data_source == "stale" else o2_pct_source

        # Gate: Stack Temp validity (spec) -- reads the same raw
        # STACK_TEMPERATURE tag PAI-S01's own ParamResult (`results` entry,
        # looked up separately below for a different purpose) is built from,
        # but judges staleness independently at the 12-row
        # TRAINING_STALE_STREAK_ROWS threshold rather than the live 3-row
        # STALE_STREAK_ROWS rule -- STACK_TEMPERATURE's whole-degree
        # quantization trips the 3-row rule on ordinary slow drift, not
        # genuine freezing (same reasoning as Cluster 1's training-exclusion
        # threshold). Scoped to this Gate 3 check only -- PAI-S01's own live
        # parameter-grid alerting for stack_temp is untouched and still
        # uses the 3-row rule. See run_efficiency()'s docstring for why
        # Stack Temp is a proxy gate today, not yet DGL's literal numeric
        # input.
        stack_temp_raw = row.get("STACK_TEMPERATURE")
        stack_temp_gate_value = None if pd.isna(stack_temp_raw) else float(stack_temp_raw)
        stack_temp_gate_stale = _update_stale(
            self._s02_stack_temp_gate_runtime, stack_temp_gate_value,
            threshold=TRAINING_STALE_STREAK_ROWS,
        )
        stack_temp_gate_source = "stale" if stack_temp_gate_stale else "real"

        # Gate: direct-vs-indirect mass-balance cross-check (spec) -- real,
        # independent "FUEL FLOW" tag, already extracted by PAI-S03's own
        # config (self._s03_view / fuel_row). Only a basic NaN check exists
        # for this tag today (matching how PAI-S03 itself treats it for
        # afr_actual) -- tagged "real" whenever present.
        fuel_flow_raw = fuel_row.get("FUEL_FLOW")
        fuel_flow_value = None if pd.isna(fuel_flow_raw) else float(fuel_flow_raw)

        # ---- Logical Filtering & Validation Rules (2026-08-13), rules 4-6
        # and 14 -- raw inputs these advisory checks need, beyond what
        # boiler_duty_fields/o2_value already carry. `cluster_row` (Steam
        # Flow A/B) and `s02_row` (SH-3 Pressure/Temp A/B, O2 LHS/RHS) are
        # both already extracted earlier in this same tick -- reused, not
        # re-read. `row` is Module 1's own replayed row (same one
        # stack_temp_gate_value/etc. already read from). Any NaN reads as
        # None, same convention as every other raw value in this method. ----
        def _f(v):
            return None if v is None or pd.isna(v) else float(v)

        ab_instruments = {
            "steam_flow_a": _f(cluster_row.get("STEAM_FLOW_A")),
            "steam_flow_b": _f(cluster_row.get("STEAM_FLOW_B")),
            "sh3_pressure_a": _f(s02_row.get("SH3_PRESSURE_A")),
            "sh3_pressure_b": _f(s02_row.get("SH3_PRESSURE_B")),
            "sh3_temp_a": _f(s02_row.get("SH3_TEMP_A")),
            "sh3_temp_b": _f(s02_row.get("SH3_TEMP_B")),
            "o2_lhs": _f(s02_row.get("O2_LHS")),
            "o2_rhs": _f(s02_row.get("O2_RHS")),
        }
        gas_path_temps = {
            "econ_inlet_c": _f(row.get("ECONOMIZER_INLET_GAS_TEMP")),
            "econ_outlet_c": _f(row.get("ECONOMIZER_OUTLET_GAS_TEMP")),
            "stack_c": _f(row.get("STACK_TEMPERATURE")),
        }
        steam_flow_history = list(self._param_runtime["steam_flow"].history)

        efficiency_result = run_efficiency(
            boiler_duty_fields, o2_value, o2_efficiency_source,
            stack_temp_data_source=stack_temp_gate_source,
            fuel_flow_tph=fuel_flow_value, fuel_flow_data_source="real",
            ab_instruments=ab_instruments, gas_path_temps=gas_path_temps,
            steam_flow_history=steam_flow_history,
        )
        self._last_efficiency_snapshot = {
            "ts": _now_iso(),
            "source_timestamp": source_ts.isoformat(),
            # Reused from Module 1's own already-computed load_pct (line
            # ~785, well before this point in the same tick) -- Phase D's
            # Trend Panel secondary axis needs unit load alongside
            # efficiency, and this is the same single-source-of-truth value
            # PAI-S01 itself displays, not an independent read.
            "unit_load_pct": round(load_pct, 1),
            **efficiency_result,
        }

        # ---- Fix 3: GCV Check WARN is a real, ack-able alert now, not just
        # a badge on the dashboard card -- same _fire_or_update_alert/
        # _mark_below_threshold/auto-clear mechanism every other alert kind
        # already uses, new "EFFICIENCY" kind so it's distinguishable in the
        # Alarm & Event Log. ----
        gcv_warn = (
            efficiency_result.get("status") == "ok"
            and efficiency_result["gcv_check"]["values"]["correction_required"]
        )
        if gcv_warn:
            g_factor = efficiency_result["gcv_check"]["values"]["g_factor"]
            self._fire_or_update_alert(
                "efficiency::gcv_check", "gcv_check", "GCV Check", "amber", "EFFICIENCY",
                f"GCV CHECK WARN — Dulong/Measured HHV factor {g_factor:.4f} outside "
                f"configured band [{GCV_CHECK_LOWER:.2f}, {GCV_CHECK_UPPER:.2f}]",
                now_mono,
            )
        else:
            self._mark_below_threshold("efficiency::gcv_check", now_mono)

        # ---- Phase A Gate 1: direct-vs-indirect mass-balance cross-check
        # (spec). Same alert mechanism as GCV Check WARN. NOTE (see
        # efficiency_engine/adapter.py's run_efficiency() assumption_notes):
        # this currently fires often -- not primarily because of real flow-
        # meter problems, but because eta_indirect still runs on a
        # placeholder fuel composition that barely moves with real
        # conditions while eta_direct (real Fuel Flow x real GCV) does. Kept
        # wired exactly per spec regardless -- becomes a genuinely
        # meaningful signal once real Ultimate/Proximate Analysis lands. ----
        mass_balance_bad = (
            efficiency_result.get("status") == "ok"
            and efficiency_result.get("direct_method", {}).get("mass_balance_discrepancy")
        )
        if mass_balance_bad:
            dm = efficiency_result["direct_method"]
            self._fire_or_update_alert(
                "efficiency::mass_balance", "mass_balance", "Mass Balance", "amber", "EFFICIENCY",
                f"MASS BALANCE DISCREPANCY — CHECK FLOW METERS — eta_direct {dm['eta_direct_hhv_pct']:.1f}% "
                f"vs eta_indirect {dm['eta_indirect_hhv_pct']:.1f}% ({dm['deviation_pct']:+.1f} pts, "
                f"threshold {dm['threshold_pct']:.1f})",
                now_mono,
            )
        else:
            self._mark_below_threshold("efficiency::mass_balance", now_mono)

        # ---- Phase D: Efficiency Alert Cards -- reuses the two EFFICIENCY-
        # kind alerts already fired above (mass_balance, gcv_check); never a
        # separate alert source, per the brief. One card per alert that is
        # currently ACTIVE (not only on the exact tick it fired), in the
        # spec's [Parameter][Current][Design][Deviation][Recommended Check]
        # format.
        #
        # Visual-consistency pass, Step 5: verified live (not assumed) that
        # the underlying gate is correct -- abs(deviation_pct) > threshold
        # genuinely drives mass_balance_bad, and the alert only stays
        # "active" past that instant because of the same AUTO_CLEAR_SECONDS
        # (30s) grace-period debounce every alert in this project already
        # uses (GCV Check WARN, CLUSTER alerts), not a bug specific to this
        # card. But a card can render mid-grace-period showing a small
        # current-tick deviation number next to "ACTIVE" with nothing
        # explaining why -- that IS a real display gap. `clearing` marks
        # exactly that state (`below_threshold_since` set but not yet past
        # AUTO_CLEAR_SECONDS) so the frontend can label it, instead of
        # looking like the threshold logic disagrees with itself. ----
        alert_cards = []
        mb_alert = self._alerts.get("efficiency::mass_balance")
        if mb_alert and mb_alert.active:
            dm = efficiency_result.get("direct_method", {})
            alert_cards.append({
                "parameter": "Mass Balance (Direct vs Indirect)",
                "current": dm.get("eta_direct_hhv_pct"),
                "current_label": "eta_direct",
                "design": dm.get("eta_indirect_hhv_pct"),
                "design_label": "eta_indirect",
                "deviation": dm.get("deviation_pct"),
                "unit": "%",
                "recommended_check": "Check Flow Meters",
                "severity": mb_alert.severity,
                "clearing": mb_alert.below_threshold_since is not None,
            })
        gcv_alert = self._alerts.get("efficiency::gcv_check")
        if gcv_alert and gcv_alert.active:
            g_factor = efficiency_result.get("gcv_check", {}).get("values", {}).get("g_factor")
            alert_cards.append({
                "parameter": "GCV Check (G-Factor)",
                "current": g_factor,
                "current_label": "g_factor",
                "design": 1.0,
                "design_label": f"band center [{GCV_CHECK_LOWER:.2f}-{GCV_CHECK_UPPER:.2f}]",
                "deviation": (g_factor - 1.0) if g_factor is not None else None,
                "unit": "",
                "recommended_check": "Verify GCV lab entry / Dulong calc inputs",
                "severity": gcv_alert.severity,
                "clearing": gcv_alert.below_threshold_since is not None,
            })
        alert_cards.sort(key=lambda c: abs(c["deviation"]) if c["deviation"] is not None else 0.0, reverse=True)
        self._last_efficiency_snapshot["alert_cards"] = alert_cards

        # Real band (Phase A follow-up): same STEADY-trained, load-binned
        # baseline already used for o2's own z-score scoring above -- mean
        # +/- std at this row's real load, not a hardcoded rule table.
        o2_band_stats = self._baseline.stats_for("o2", load_pct)
        o2_band_low = o2_band_stats.mean - o2_band_stats.std
        o2_band_high = o2_band_stats.mean + o2_band_stats.std
        o2_dev = o2_value - o2_target

        base_co = 60.0 + random.uniform(-15, 25)
        if active_scenario == "Under-Air / CO Risk Event":
            # Capped term + recalibrated boost, this scenario only -- see
            # UNDER_AIR_SCENARIO_CO_TERM_CAP's comment for why (the general,
            # uncapped term below overshoots CO_CRITICAL almost always once
            # combined with this scenario's own O2 bias).
            if o2_dev < -0.5:
                base_co += min(UNDER_AIR_SCENARIO_CO_TERM_CAP, (abs(o2_dev) ** 2.2) * 180.0)
            base_co += UNDER_AIR_SCENARIO_CO_FLAT_BOOST
        elif active_scenario == "Severe Under-Air / CO Critical Event":
            # Deterministic target, not the shared o2_dev-linked term at all
            # -- this scenario's whole job is reliably clearing P1's CO
            # threshold, not modeling a naturalistic CO response.
            base_co = SEVERE_UNDER_AIR_CO_TARGET_PPM + random.uniform(-SEVERE_UNDER_AIR_CO_NOISE_PPM, SEVERE_UNDER_AIR_CO_NOISE_PPM)
        else:
            if o2_dev < -0.5:
                base_co += (abs(o2_dev) ** 2.2) * 180.0
            if active_scenario == "Excess Air Event":
                base_co = max(20.0, base_co - 30.0)
        self._co_ppm = max(0.0, self._co_ppm * 0.5 + base_co * 0.5)
        self._co_history.append(round(self._co_ppm, 1))

        # PAI-S02 Gate 3B (Phase B): the efficiency snapshot above was built
        # before combustion's co_ppm for THIS tick existed yet (co_ppm is
        # computed here, later in the same _tick()), so its Incomplete
        # Combustion flag is patched in place now rather than reusing last
        # tick's value -- same single-source-of-truth-per-tick discipline as
        # every other shared value, just applied after the fact instead of
        # before, since co_ppm has no PAI-S01-equivalent hoisting point.
        if self._last_efficiency_snapshot.get("status") == "ok":
            self._last_efficiency_snapshot["zone"]["flags"]["co_incomplete_combustion"] = (
                classify_co_flag(self._co_ppm, "simulated")
            )

        if self._co_ppm > 500:
            quadrant = {"id": "CO_CRITICAL", "label": "CO CRITICAL", "color": "red"}
        elif -0.5 <= o2_dev <= 1.5 and self._co_ppm < 200:
            quadrant = {"id": "Q1", "label": "Optimal", "color": "green"}
        elif o2_dev < -1.0 and self._co_ppm > 300:
            quadrant = {"id": "Q2", "label": "Dangerous — Under-Fired", "color": "red"}
        elif o2_dev > 2.0 and self._co_ppm < 200:
            quadrant = {"id": "Q3", "label": "Wasteful — Reduce Air", "color": "amber"}
        elif o2_dev > 2.0 and self._co_ppm > 300:
            quadrant = {"id": "Q4", "label": "Abnormal — Mixing Issue", "color": "red"}
        else:
            quadrant = {"id": "Q0", "label": "Transitional", "color": "amber"}
        self._quadrant_trail.append({"x": round(o2_dev, 2), "y": round(self._co_ppm, 1)})

        stack_result = next(r for r in results if r.key == "stack_temp")
        stack_temp_value = stack_result.value if stack_result.valid else stack_result.expected

        # ---- Phase D: Daily/Shift Summary Table accumulator update -- only
        # on a tick where PAI-S02 actually computed ("ok"), so every column
        # in a shift's row comes from the same set of ticks (no mixing an
        # eta average from fewer ticks than the O2/Stack Temp/CO averages).
        # "FA Carbon" uses unburned_carbon_loss_pct -- see decisions.md's
        # Phase C note: this is the library's single combined
        # unburned-carbon figure across all 4 ash streams, not a
        # fly-ash-specific number (that split doesn't exist yet -- Awes ask
        # list). Labeled accordingly in the frontend, not silently implied
        # to be fly-ash-only.
        #
        # "GCV" uses FUEL_HHV_KCAL_KG (fuel.hhv_kj_kg's kcal/kg form) -- the
        # GCV that actually feeds eta/DGL/every other column in this same
        # row, via the library's own calculation. NOT GCV_KCAL_PER_KG
        # (Gate 1's deliberately-independent Q_input source, decisions.md
        # #43) -- that constant predates the 2026-08-13 real-fuel-data
        # wiring and was simply the only GCV value that existed when this
        # table was first built (Phase D); left unrevisited until now, not
        # a deliberate choice the way Gate 1's independence is. Fixed
        # 2026-08-14 so this column matches the GCV Check card's own
        # "Measured HHV" figure instead of showing an unrelated number. ----
        if efficiency_result.get("status") == "ok":
            shift_id, shift_label = _shift_key(source_ts)
            bucket = self._shift_stats.setdefault(shift_id, {
                "label": shift_label, "sum_eta": 0.0, "sum_dgl": 0.0,
                "sum_fa_carbon": 0.0, "sum_gcv": 0.0, "sum_o2": 0.0,
                "sum_stack_temp": 0.0, "sum_co": 0.0, "count": 0,
                "first_ts": source_ts.isoformat(),
            })
            eff_vals = efficiency_result["efficiency"]["values"]
            bucket["sum_eta"] += eff_vals["boiler_efficiency_hhv_pct"]
            bucket["sum_dgl"] += eff_vals["dry_flue_gas_loss_pct"]
            bucket["sum_fa_carbon"] += eff_vals["unburned_carbon_loss_pct"]
            bucket["sum_gcv"] += FUEL_HHV_KCAL_KG
            bucket["sum_o2"] += o2_value
            bucket["sum_stack_temp"] += stack_temp_value
            bucket["sum_co"] += self._co_ppm
            bucket["count"] += 1
            bucket["last_ts"] = source_ts.isoformat()

        rows_sorted = sorted(self._shift_stats.values(), key=lambda b: b["last_ts"], reverse=True)[:12]
        self._last_efficiency_snapshot["shift_summary"] = [
            {
                "label": b["label"],
                "avg_eta_pct": round(b["sum_eta"] / b["count"], 2),
                "avg_dgl_pct": round(b["sum_dgl"] / b["count"], 3),
                "avg_fa_carbon_pct": round(b["sum_fa_carbon"] / b["count"], 3),
                "avg_gcv_kcal_kg": round(b["sum_gcv"] / b["count"], 0),
                "avg_o2_pct": round(b["sum_o2"] / b["count"], 2),
                "avg_stack_temp_c": round(b["sum_stack_temp"] / b["count"], 1),
                "avg_co_ppm": round(b["sum_co"] / b["count"], 1),
                "eta_deviation_pct": round(ETA_DESIGN_PCT - (b["sum_eta"] / b["count"]), 2),
                "n_ticks": b["count"],
            }
            for b in rows_sorted
        ]

        # ---- afr_actual: REAL now (Phase A) -- Total Air Flow / Fuel Flow,
        # both real/derived. Falls back to the old simulated formula only if
        # a row's real inputs are missing (rare -- both tags are dense).
        total_air_flow_raw = row.get("TOTAL_AIR_FLOW")
        total_air_flow_value = None if pd.isna(total_air_flow_raw) else float(total_air_flow_raw)
        fuel_flow_raw = fuel_row.get("FUEL_FLOW")
        fuel_flow_value = None if pd.isna(fuel_flow_raw) else float(fuel_flow_raw)
        if total_air_flow_value is not None and fuel_flow_value is not None and fuel_flow_value > 0:
            afr_actual_value = total_air_flow_value / fuel_flow_value
            afr_actual_source = "real"
        else:
            afr_actual_value = _afr(o2_value)
            afr_actual_source = "simulated"

        # ---- Layer 2 (5-min) cadence: css + efficiency held steady between
        # recomputes, per the PAI-S03 Dashboard_Method spec (see docstring). ----
        if self._layer2_last_mono is None or (now_mono - self._layer2_last_mono) >= LAYER2_INTERVAL_SECONDS:
            self._layer2_cache["css"] = _css(o2_value, o2_target, self._co_ppm, quadrant)
            self._layer2_cache["efficiency"] = _efficiency_impact(o2_value, o2_target, stack_temp_value, load_mw)
            self._layer2_last_mono = now_mono
        css_value = self._layer2_cache["css"]
        efficiency_value = self._layer2_cache["efficiency"]

        # ---- Layer 3 (per-shift) cadence hook: afr_design. Formula is
        # STILL the old simulated one (needs Carbon%/Hydrogen% from Ultimate
        # Analysis, not yet available) -- only the recompute cadence is new,
        # so Phase B can drop in real logic here without restructuring. ----
        if self._layer3_last_mono is None or (now_mono - self._layer3_last_mono) >= LAYER3_INTERVAL_SECONDS:
            self._afr_design_cache = _afr(o2_target)
            self._layer3_last_mono = now_mono
        afr_design_value = self._afr_design_cache

        # ---- Alert Priority Matrix (P1-P5) -- replaces the old single
        # co_ppm>500 "co::critical" alert. P2/P3 are real (O2-only); P1/P4
        # are CO-gated, still simulated (see module docstring). Dedup via
        # the same _fire_or_update_alert/_mark_below_threshold pattern
        # Module 1 already uses; combustion alerts additionally get a
        # 30-min ack-snooze (_check_combustion_ack_snooze below), which
        # Module 1's other alert kinds don't have. ----
        p1_condition = o2_value < P1_O2_PCT_MAX and self._co_ppm > P1_CO_PPM_MIN
        if p1_condition:
            self._fire_or_update_alert(
                "combustion::p1", "combustion_p1", "Combustion P1", "red", "COMBUSTION",
                f"P1 UNDER-FIRED ALARM — INCREASE AIR IMMEDIATELY (O2 {o2_value:.1f}%, CO {self._co_ppm:.0f} ppm)",
                now_mono, priority="P1",
            )
        else:
            self._mark_below_threshold("combustion::p1", now_mono)

        p2_condition_now = o2_value > (o2_target + P2_O2_DEV_PCT_ABOVE)
        if p2_condition_now:
            if self._p2_condition_since is None:
                self._p2_condition_since = now_mono
        else:
            self._p2_condition_since = None
        p2_sustained = p2_condition_now and self._p2_condition_since is not None and (
            now_mono - self._p2_condition_since
        ) >= P2_SUSTAINED_SECONDS
        if p2_sustained:
            self._fire_or_update_alert(
                "combustion::p2", "combustion_p2", "Combustion P2", "red", "COMBUSTION",
                f"P2 EXCESS AIR ACTION — O2 {o2_value:.1f}% ({o2_value - o2_target:+.1f} pts above target) sustained >=10 min",
                now_mono, priority="P2",
            )
        else:
            self._mark_below_threshold("combustion::p2", now_mono)

        p3_condition_now = not (o2_band_low <= o2_value <= o2_band_high)
        if p3_condition_now:
            if self._p3_condition_since is None:
                self._p3_condition_since = now_mono
        else:
            self._p3_condition_since = None
        p3_sustained = p3_condition_now and self._p3_condition_since is not None and (
            now_mono - self._p3_condition_since
        ) >= P3_SUSTAINED_SECONDS
        if p3_sustained:
            self._fire_or_update_alert(
                "combustion::p3", "combustion_p3", "Combustion P3", "amber", "COMBUSTION",
                f"P3 O2 DEVIATION — INVESTIGATE — O2 {o2_value:.1f}% outside band [{o2_band_low:.1f}, {o2_band_high:.1f}] sustained >=5 min",
                now_mono, priority="P3",
            )
        else:
            self._mark_below_threshold("combustion::p3", now_mono)

        p4_condition_now = self._co_ppm > P4_CO_PPM_MIN
        if p4_condition_now:
            if self._p4_condition_since is None:
                self._p4_condition_since = now_mono
        else:
            self._p4_condition_since = None
        p4_sustained = p4_condition_now and self._p4_condition_since is not None and (
            now_mono - self._p4_condition_since
        ) >= P4_SUSTAINED_SECONDS
        if p4_sustained:
            self._fire_or_update_alert(
                "combustion::p4", "combustion_p4", "Combustion P4", "amber", "COMBUSTION",
                f"P4 CO ELEVATED — CHECK COMBUSTION — CO {self._co_ppm:.0f} ppm sustained >=3 min",
                now_mono, priority="P4",
            )
        else:
            self._mark_below_threshold("combustion::p4", now_mono)

        # P5 (soot blowing / mill change): mode-only, no alert -- this unit
        # has no soot blower and is a CFBC design (no pulverizer mills), so
        # there's no real trigger condition here. Hook kept for other
        # plants/units where it would apply -- structurally inert here by
        # design, not an oversight (see module docstring).

        self._check_combustion_ack_snooze(now_mono)

        # ---- Cluster 1 cross-parameter validation -- a SEPARATE signal
        # from the BOI/parameter scoring above: it checks relationships
        # BETWEEN parameters (e.g. does Steam Flow-A agree with Steam
        # Flow-B?), not one parameter's deviation from its own baseline.
        # Deliberately not folded into boi_result or any single parameter's
        # sub_score -- see this module's docstring / the integration brief
        # this was built from for why conflating the two would double-count
        # the same underlying issue. ----
        cluster_results = validate_cluster_row(cluster_row, self._cluster_baseline, self._cluster_config)
        cross_validation_payload: list[dict[str, Any]] = []
        for rel_key, result in cluster_results.items():
            meta = CLUSTER_RELATIONSHIP_META[rel_key]
            note = _cluster_note(rel_key, result.status, result.detail)
            cross_validation_payload.append({
                "relationship": rel_key,
                "name": meta["name"],
                "status": result.status,
                "members": meta["members"],
                "note": note,
            })
            alert_id = f"cluster::{rel_key}"
            if result.status == "outlier":
                self._fire_or_update_alert(
                    alert_id, rel_key, meta["name"], "red", "CLUSTER",
                    f"{meta['name']}: {note}", now_mono,
                )
            elif result.status == "ambiguous":
                self._fire_or_update_alert(
                    alert_id, rel_key, meta["name"], "amber", "CLUSTER",
                    f"{meta['name']}: {note}", now_mono,
                )
            else:
                self._mark_below_threshold(alert_id, now_mono)

        # ---- auto-clear ----
        for a in self._alerts.values():
            if a.active and a.below_threshold_since is not None:
                if now_mono - a.below_threshold_since >= AUTO_CLEAR_SECONDS:
                    a.active = False
                    a.cleared_ts = _now_iso()

        # ---- assemble snapshot ----
        self._last_snapshot = {
            "ts": _now_iso(),
            "source_timestamp": source_ts.isoformat(),
            "unit_load_pct": round(load_pct, 1),
            "unit_load_mw": round(load_mw, 1),
            "mcr_mw": MCR_MW,
            "mode": self._mode,
            "mode_since": self._mode_since,
            "mode_duration_sec": int(now_mono - self._mode_since_mono),
            "mode_notes": MODE_VALIDATION_NOTES,
            "scenario": self._scenario,
            "active_scenario": active_scenario,
            "scenario_note": SCENARIO_NOTES.get(active_scenario),
            "data_quality_pct": boi_result.data_quality_pct,
            "safety_data_incomplete": boi_result.safety_data_incomplete,
            "boi": {
                "value": boi_result.value,
                "zone": boi_result.zone,
                "suppressed": boi_result.suppressed,
                "trend": self._boi_trend(),
            },
            "boi_history": list(self._boi_history),
            "parameters": [self._param_payload(r) for r in results],
            "deviation_waterfall": boi_result.contributions,
            "combustion": {
                "o2_pct": round(o2_value, 2),
                "o2_target": round(o2_target, 2),
                "o2_band_low": o2_band_low,
                "o2_band_high": o2_band_high,
                "excess_air_pct": round(_excess_air(o2_value), 1),
                "co_ppm": round(self._co_ppm, 1),
                "co_history": list(self._co_history),
                "quadrant": quadrant,
                "quadrant_trail": list(self._quadrant_trail),
                "afr_actual": round(afr_actual_value, 2),
                "afr_design": round(afr_design_value, 2),
                "css": round(css_value, 1),
                "efficiency": efficiency_value,
                "guidance": _operator_guidance(o2_value, o2_target, self._co_ppm, efficiency_value),
                # Vocabulary (same spirit as scoring.DataSource -- never let a
                # value's provenance be inferable only from a code comment):
                #   real             -- a real tag, or a pure function of only
                #                       real tags/real learned baselines.
                #   simulated        -- fabricated/placeholder; no real input
                #                       feeds it at all.
                #   derived_estimate -- computed FROM real inputs, but via an
                #                       approximate/uncalibrated proxy formula
                #                       (not a measured or plant-validated
                #                       value) -- e.g. fd_damper_reduction_pct
                #                       below, which stands in for a real
                #                       damper-position curve this dataset
                #                       doesn't have.
                #   partial          -- object-level only: this composite has
                #                       a mix of the above among its parts.
                "data_source": {
                    "o2_pct": o2_pct_source,  # "simulated" only while Under-Air/CO scenario is active, "real" otherwise
                    "o2_target": "real",
                    "o2_band_low": "real",   # STEADY-trained, load-binned baseline mean +/- std (same baseline as o2's own z-score scoring)
                    "o2_band_high": "real",
                    "excess_air_pct": o2_pct_source,  # EA = O2/(21-O2)*100, pure function of o2_pct -- inherits its scenario-time flag
                    "co_ppm": "simulated",
                    "co_history": "simulated",
                    "quadrant": "simulated",
                    "quadrant_trail": "simulated",
                    "afr_actual": afr_actual_source,
                    "afr_design": "simulated",
                    "css": "partial",
                    "efficiency.excess_o2_pct": "real",
                    "efficiency.dry_gas_loss_delta_pct": "real",
                    "efficiency.avoidable_heat_kcal_hr": "real",
                    "efficiency.avoidable_cost_inr_per_hr": "simulated",
                    "guidance": "partial",
                    # The one value guidance's text computes that ISN'T just a
                    # re-display of an already-flagged field above (X/Y/Z/B/C/D
                    # all reuse o2_pct/o2_target/excess_air_pct/efficiency.*/
                    # co_ppm, already flagged): the FD damper reduction % (A)
                    # in the HIGH O2 template. No calibrated damper-position
                    # curve exists in this data -- it's approximated as the
                    # excess-air-percentage-point delta between current and
                    # target O2. Built entirely from real O2/target, but an
                    # approximation, not a measured or validated value --
                    # flagged distinctly so it can't be mistaken for either
                    # "real" (measured) or "simulated" (fabricated).
                    "guidance.fd_damper_reduction_pct": "derived_estimate",
                },
            },
            "cross_validation": cross_validation_payload,
            "alerts": self._alert_payload(),
        }

    # ---------- helpers ----------
    def _param_payload(self, result: ParamResult) -> dict[str, Any]:
        rt = self._param_runtime[result.key]
        avg = (rt.day_sum / rt.day_count) if rt.day_count else result.value
        return {
            "key": result.key,
            "name": result.name,
            "unit": result.unit,
            "weight": result.weight,
            "safety": result.safety,
            "value": round(result.value, 2),
            "expected": round(result.expected, 2),
            "deviation_pct": round(result.deviation_pct, 2),
            "zone": result.zone,
            "sub_score": round(result.sub_score, 1),
            "valid": result.valid,
            "data_source": result.data_source,
            "history": list(rt.history),
            "day_min": round(rt.day_min, 2) if rt.day_count else None,
            "day_max": round(rt.day_max, 2) if rt.day_count else None,
            "day_avg": round(avg, 2),
        }

    def _boi_trend(self) -> str:
        if len(self._boi_history) < 2:
            return "flat"
        a = self._boi_history[-1]["boi"]
        b = self._boi_history[-2]["boi"]
        if a - b > 0.5:
            return "up"
        if a - b < -0.5:
            return "down"
        return "flat"

    def _fire_or_update_alert(
        self, alert_id: str, key: str, name: str, severity: str, kind: str, message: str, now_mono: float,
        priority: str | None = None,
    ) -> None:
        existing = self._alerts.get(alert_id)
        if existing and existing.active:
            existing.severity = severity
            existing.message = message
            existing.last_update_ts = _now_iso()
            existing.below_threshold_since = None
            existing.priority = priority
            return
        self._alerts[alert_id] = Alert(
            id=alert_id,
            parameter_key=key,
            parameter_name=name,
            severity=severity,
            kind=kind,
            message=message,
            first_ts=_now_iso(),
            last_update_ts=_now_iso(),
            priority=priority,
        )

    def _check_combustion_ack_snooze(self, now_mono: float) -> None:
        """COMBUSTION-kind alerts only (see module docstring): an
        acknowledged alert that's still active COMBUSTION_ACK_SNOOZE_SECONDS
        after it was acked re-arms (acknowledged -> False) automatically.
        Module 1's other alert kinds never call this -- they stay
        acknowledged until the underlying condition clears, unchanged.
        """
        for a in self._alerts.values():
            if (
                a.kind == "COMBUSTION" and a.active and a.acknowledged
                and a.acknowledged_mono is not None
                and (now_mono - a.acknowledged_mono) >= COMBUSTION_ACK_SNOOZE_SECONDS
            ):
                a.acknowledged = False
                a.acknowledged_mono = None

    def _mark_below_threshold(self, alert_id: str, now_mono: float) -> None:
        a = self._alerts.get(alert_id)
        if not a or not a.active:
            return
        if a.below_threshold_since is None:
            a.below_threshold_since = now_mono

    def _alert_payload(self) -> list[dict[str, Any]]:
        out = []
        for a in sorted(self._alerts.values(), key=lambda a: a.first_ts, reverse=True):
            out.append({
                "id": a.id,
                "parameter_key": a.parameter_key,
                "parameter_name": a.parameter_name,
                "severity": a.severity,
                "kind": a.kind,
                "message": a.message,
                "first_ts": a.first_ts,
                "last_update_ts": a.last_update_ts,
                "cleared_ts": a.cleared_ts,
                "active": a.active,
                "acknowledged": a.acknowledged,
                "priority": a.priority,
            })
        return out[:50]

    # ---------- public API ----------
    def snapshot(self) -> dict[str, Any]:
        return self._last_snapshot

    def efficiency_snapshot(self) -> dict[str, Any]:
        return self._last_efficiency_snapshot

    @property
    def scenarios(self) -> list[str]:
        return SCENARIOS


state_builder = RealDataStateBuilder()
