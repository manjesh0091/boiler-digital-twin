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

Combustion — flagging a deliberate deviation from a literal "leave
combustion untouched" reading. Building it fully decoupled from real data
would mean parameters['o2'] (now real historian data) and
combustion['o2_pct'] (fully fake, independent) show two different O2
readings on two different dashboard pages for what's supposedly the same
sensor. That seemed like a worse bug than the scope question, so:
combustion.o2_pct mirrors the real parameters['o2'].value, and o2_target
uses the same baseline.expected('o2', load) as the parameter grid.
Everything downstream of O2 (CO ppm random walk, quadrant classification,
AFR, CSS, efficiency impact, operator guidance, o2_band_low/high) is the
OLD simulated logic, UNCHANGED, just fed the real o2/target instead of a
fake independent walk. Please confirm this is the right call.

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
from shared.data_quality import STALE_STREAK_ROWS
from shared.feature_extraction import load_config
from shared.raw_loader import load_raw

DATA_PATH = Path(__file__).parent.parent / "data" / "processed" / "module1_features.csv"
CLUSTER_CONFIG_PATH = Path(__file__).parent.parent / "clusters" / "cluster_config.yaml"

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
    "Drum Level Excursion",
    "Soot Blowing Period",
    "Sensor Data Quality Drop",
]

SCENARIO_NOTES: dict[str, str | None] = {
    "Normal Operation": None,
    "Excess Air Event": None,
    "Under-Air / CO Risk Event": None,
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

AMBIENT_TEMP = 30.0
GCV = 4000.0
COAL_COST_INR_PER_KG = 6.5
STEAM_TO_COAL = 6.5


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

def _o2_band(load_frac: float) -> tuple[float, float]:
    if load_frac >= 0.80:
        return (2.5, 5.5)
    if load_frac >= 0.60:
        return (3.0, 6.0)
    if load_frac >= 0.40:
        return (3.5, 6.5)
    if load_frac >= 0.25:
        return (4.0, 8.0)
    return (5.0, 10.0)


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
    avoidable_cost = coal_kg_hr * (dgl_delta / 100.0) * COAL_COST_INR_PER_KG
    return {
        "excess_o2_pct": round(excess, 2),
        "dry_gas_loss_delta_pct": round(dgl_delta, 3),
        "avoidable_cost_inr_per_hr": round(avoidable_cost, 0),
    }


def _operator_guidance(o2: float, target: float, co: float) -> dict[str, str]:
    if co > 500:
        return {"level": "critical", "text": f"CO at {co:.0f} ppm — verify air supply, do NOT reduce further until CO confirmed safe."}
    if o2 < target - 1.0 and co > 300:
        return {"level": "critical", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%), CO at {co:.0f} ppm — increase FD damper cautiously."}
    if o2 > target + 2.0:
        return {"level": "warning", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%). Consider reducing FD damper position to cut dry gas loss."}
    if o2 < target - 0.5:
        return {"level": "warning", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%). Trending under-air — monitor CO closely."}
    return {"level": "ok", "text": f"O₂ at {o2:.1f}% within target band ({target:.1f}%). Combustion trim optimal."}


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
    kind: str              # "param" | "composite" | "safety" | "co" | "CLUSTER"
    message: str
    first_ts: str
    last_update_ts: str
    active: bool = True
    acknowledged: bool = False
    cleared_ts: str | None = None
    below_threshold_since: float | None = None  # monotonic seconds


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

        self._param_runtime: dict[str, ParamRuntimeState] = {k: ParamRuntimeState(k) for k in CSV_COLUMN}
        self._boi_history: Deque[dict[str, float]] = deque(maxlen=HISTORY_LEN)
        self._alerts: dict[str, Alert] = {}

        self._mode: str | None = None
        self._mode_since = _now_iso()
        self._mode_since_mono = time.monotonic()

        self._scenario = "Normal Operation"

        # combustion subsystem's own bit of state -- simulated, see module docstring
        self._co_ppm = 80.0
        self._co_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self._quadrant_trail: Deque[dict[str, float]] = deque(maxlen=25)

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
            return True

    async def acknowledge_all(self) -> int:
        async with self._lock:
            n = 0
            for a in self._alerts.values():
                if a.active and not a.acknowledged:
                    a.acknowledged = True
                    n += 1
            return n

    # ---------- tick ----------
    def _tick(self) -> None:
        now_mono = time.monotonic()
        row = self._df.iloc[self._row_idx]
        cluster_row = self._cluster_view.iloc[self._row_idx]
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
            if actual is not None and rt.last_raw is not None and actual == rt.last_raw:
                rt.stale_streak += 1
            else:
                rt.stale_streak = 0
            rt.last_raw = actual
            is_stale = rt.stale_streak >= STALE_STREAK_ROWS
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
        o2_band_low, o2_band_high = _o2_band(load_frac)
        o2_dev = o2_value - o2_target

        base_co = 60.0 + random.uniform(-15, 25)
        if o2_dev < -0.5:
            base_co += (abs(o2_dev) ** 2.2) * 180.0
        if active_scenario == "Under-Air / CO Risk Event":
            base_co += 350.0
        if active_scenario == "Excess Air Event":
            base_co = max(20.0, base_co - 30.0)
        self._co_ppm = max(0.0, self._co_ppm * 0.5 + base_co * 0.5)
        self._co_history.append(round(self._co_ppm, 1))

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

        if self._co_ppm > 500:
            self._fire_or_update_alert(
                "co::critical", "co", "CO Emissions", "red", "co",
                f"CO at {self._co_ppm:.0f} ppm — combustion safety hazard", now_mono,
            )
        else:
            self._mark_below_threshold("co::critical", now_mono)

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
                "afr_actual": round(_afr(o2_value), 2),
                "afr_design": round(_afr(o2_target), 2),
                "css": round(_css(o2_value, o2_target, self._co_ppm, quadrant), 1),
                "efficiency": _efficiency_impact(o2_value, o2_target, stack_temp_value, load_mw),
                "guidance": _operator_guidance(o2_value, o2_target, self._co_ppm),
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
    ) -> None:
        existing = self._alerts.get(alert_id)
        if existing and existing.active:
            existing.severity = severity
            existing.message = message
            existing.last_update_ts = _now_iso()
            existing.below_threshold_since = None
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
        )

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
            })
        return out[:50]

    # ---------- public API ----------
    def snapshot(self) -> dict[str, Any]:
        return self._last_snapshot

    @property
    def scenarios(self) -> list[str]:
        return SCENARIOS


state_builder = RealDataStateBuilder()
