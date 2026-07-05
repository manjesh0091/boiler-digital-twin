"""
Boiler Digital Twin simulation engine.

Generates physically-plausible sensor telemetry driven by a slowly-varying
Unit Load, computes the composite BOI score, combustion metrics, and
manages a persistent alarm log with debounced auto-clear and dedup.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque


# ---------- Parameter configuration ----------
# Each parameter has an expected-value function of load fraction (0..1)
# and threshold bands used both for zoning and sub-score computation.

def _expected_steam_pressure(load: float) -> float:  # kg/cm²
    return 90.0 + 50.0 * load  # 90 at 0%, 140 at 100%

def _expected_steam_temp(load: float) -> float:  # °C
    return 500.0 + 40.0 * load  # 500..540

def _expected_steam_flow(load: float) -> float:  # t/h
    return 300.0 * load  # linear

def _expected_feedwater_flow(load: float) -> float:  # t/h
    return 305.0 * load  # slightly higher than steam

def _expected_drum_pressure(load: float) -> float:  # kg/cm²
    return 95.0 + 50.0 * load

def _expected_drum_level(load: float) -> float:  # mm from setpoint
    return 0.0

def _expected_furnace_draft(load: float) -> float:  # mmWC (negative)
    return -6.0 - 2.0 * load  # -6..-8

def _expected_o2(load: float) -> float:  # % vol
    if load >= 0.80:
        return 3.5
    if load >= 0.60:
        return 4.0
    if load >= 0.40:
        return 4.5
    if load >= 0.25:
        return 5.5
    return 6.5

def _expected_stack_temp(load: float) -> float:  # °C
    return 145.0 - 10.0 * load  # 145 at 0%, 135 at 100%

def _expected_fegt(load: float) -> float:  # °C
    return 950.0 + 100.0 * load  # 950..1050


PARAMS: list[dict[str, Any]] = [
    {"key": "steam_pressure",  "name": "Main Steam Pressure",   "unit": "kg/cm²", "weight": 0.12, "expected": _expected_steam_pressure,  "amber_pct": 3.0, "red_pct": 7.0, "safety": False},
    {"key": "steam_temp",      "name": "Main Steam Temperature","unit": "°C",     "weight": 0.12, "expected": _expected_steam_temp,      "amber_pct": 2.0, "red_pct": 5.0, "safety": False},
    {"key": "steam_flow",      "name": "Main Steam Flow",       "unit": "t/h",    "weight": 0.10, "expected": _expected_steam_flow,      "amber_pct": 4.0, "red_pct": 9.0, "safety": False},
    {"key": "feedwater_flow",  "name": "Feedwater Flow",        "unit": "t/h",    "weight": 0.08, "expected": _expected_feedwater_flow,  "amber_pct": 5.0, "red_pct": 10.0, "safety": False},
    {"key": "drum_pressure",   "name": "Drum Pressure",         "unit": "kg/cm²", "weight": 0.00, "expected": _expected_drum_pressure,   "amber_pct": 3.0, "red_pct": 7.0, "safety": False},
    {"key": "drum_level",      "name": "Drum Level",            "unit": "mm",     "weight": 0.15, "expected": _expected_drum_level,      "amber_abs": 30.0, "red_abs": 60.0, "safety": True},
    {"key": "furnace_draft",   "name": "Furnace Draft",         "unit": "mmWC",   "weight": 0.15, "expected": _expected_furnace_draft,   "amber_abs": 3.0,  "red_abs": 6.0,  "safety": True},
    {"key": "o2",              "name": "Flue Gas O₂",           "unit": "% vol",  "weight": 0.12, "expected": _expected_o2,              "amber_abs": 1.0,  "red_abs": 2.5,  "safety": False},
    {"key": "stack_temp",      "name": "Stack Temperature",     "unit": "°C",     "weight": 0.08, "expected": _expected_stack_temp,      "amber_pct": 5.0,  "red_pct": 12.0, "safety": False},
    {"key": "fegt",            "name": "FEGT",                  "unit": "°C",     "weight": 0.08, "expected": _expected_fegt,            "amber_pct": 3.0,  "red_pct": 6.0,  "safety": False},
]

PARAM_BY_KEY = {p["key"]: p for p in PARAMS}
HISTORY_LEN = 60  # sparkline points

SCENARIOS = [
    "Normal Operation",
    "Excess Air Event",
    "Under-Air / CO Risk Event",
    "Drum Level Excursion",
    "Soot Blowing Period",
    "Sensor Data Quality Drop",
]

MCR_MW = 150.0  # rated maximum continuous load in MW
AMBIENT_TEMP = 30.0
GCV = 4000.0
COAL_COST_INR_PER_KG = 6.5
STEAM_TO_COAL = 6.5  # rough kg-coal per kg-steam factor for illustrative cost math


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_zone(param: dict[str, Any], actual: float, expected: float) -> tuple[str, float, float]:
    """Return (zone, deviation_pct, sub_score 0..100)."""
    if "amber_abs" in param:
        dev = actual - expected
        dev_abs = abs(dev)
        amber = param["amber_abs"]
        red = param["red_abs"]
        # deviation_pct expressed relative to red threshold for the waterfall/UX consistency
        dev_pct = (dev_abs / red) * 100.0 if red else 0.0
        if dev_abs <= amber:
            sub = 100.0 - (dev_abs / amber) * 20.0  # 100..80 within green
            zone = "green"
        elif dev_abs <= red:
            sub = 80.0 - ((dev_abs - amber) / (red - amber)) * 60.0  # 80..20
            zone = "amber"
        else:
            sub = max(0.0, 20.0 - ((dev_abs - red) / red) * 20.0)
            zone = "red"
        return zone, dev_pct if dev >= 0 else -dev_pct, sub

    # percent-based
    if expected == 0:
        return "green", 0.0, 100.0
    dev_pct = (actual - expected) / expected * 100.0
    dev_abs = abs(dev_pct)
    amber = param["amber_pct"]
    red = param["red_pct"]
    if dev_abs <= amber:
        sub = 100.0 - (dev_abs / amber) * 20.0
        zone = "green"
    elif dev_abs <= red:
        sub = 80.0 - ((dev_abs - amber) / (red - amber)) * 60.0
        zone = "amber"
    else:
        sub = max(0.0, 20.0 - ((dev_abs - red) / red) * 20.0)
        zone = "red"
    return zone, dev_pct, sub


@dataclass
class ParamState:
    key: str
    value: float = 0.0
    expected: float = 0.0
    deviation_pct: float = 0.0
    zone: str = "green"
    sub_score: float = 100.0
    valid: bool = True
    history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    ts_history: Deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))
    day_min: float = math.inf
    day_max: float = -math.inf
    day_sum: float = 0.0
    day_count: int = 0


@dataclass
class Alert:
    id: str
    parameter_key: str
    parameter_name: str
    severity: str          # "amber" | "red"
    kind: str              # "param" | "composite" | "safety" | "co"
    message: str
    first_ts: str
    last_update_ts: str
    active: bool = True
    acknowledged: bool = False
    cleared_ts: str | None = None
    below_threshold_since: float | None = None  # monotonic seconds


class BoilerSimulator:
    """Runs the full simulation loop asynchronously, keeps state in memory."""

    TICK_SECONDS = 2.0
    AUTO_CLEAR_SECONDS = 30.0   # simulated ~5 min of stability

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._t0 = time.monotonic()
        self._scenario = "Normal Operation"
        self._scenario_started = time.monotonic()
        self._auto_event_next = time.monotonic() + random.uniform(60.0, 90.0)
        self._auto_event_active_until = 0.0
        self._auto_event_current: str | None = None

        self._mode = "Steady State"
        self._mode_since = _now_iso()
        self._mode_since_mono = time.monotonic()

        self._unit_load_pct = 0.75
        self._load_target = 0.75

        # Combustion extras
        self._co_ppm = 80.0
        self._co_history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self._quadrant_trail: Deque[dict[str, float]] = deque(maxlen=25)
        self._boi_history: Deque[dict[str, float]] = deque(maxlen=HISTORY_LEN)

        self._params: dict[str, ParamState] = {p["key"]: ParamState(key=p["key"]) for p in PARAMS}
        self._alerts: dict[str, Alert] = {}

        self._task: asyncio.Task | None = None

    # ---------- lifecycle ----------
    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        try:
            # seed history so sparklines have shape immediately
            for _ in range(HISTORY_LEN):
                self._tick(seed=True)
            while True:
                await asyncio.sleep(self.TICK_SECONDS)
                async with self._lock:
                    self._tick()
        except asyncio.CancelledError:
            return

    # ---------- controls ----------
    async def set_scenario(self, scenario: str) -> None:
        async with self._lock:
            if scenario not in SCENARIOS:
                scenario = "Normal Operation"
            self._scenario = scenario
            self._scenario_started = time.monotonic()
            if scenario == "Soot Blowing Period":
                self._set_mode("Soot Blowing")
            elif scenario == "Normal Operation":
                self._set_mode(self._mode_from_load(self._unit_load_pct))

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

    # ---------- helpers ----------
    def _mode_from_load(self, load: float) -> str:
        if load < 0.25:
            return "Startup"
        if load < 0.40:
            return "Low Load"
        return "Steady State"

    def _set_mode(self, mode: str) -> None:
        if mode != self._mode:
            self._mode = mode
            self._mode_since = _now_iso()
            self._mode_since_mono = time.monotonic()

    # ---------- tick ----------
    def _tick(self, seed: bool = False) -> None:
        now_mono = time.monotonic()
        elapsed = now_mono - self._t0

        # ---- Unit load: sinusoidal + noise + occasional ramp targets ----
        base = 0.72 + 0.22 * math.sin(elapsed / 90.0)  # 6-minute-ish cycle
        base += 0.02 * math.sin(elapsed / 17.0)
        base += random.uniform(-0.01, 0.01)
        self._unit_load_pct = max(0.15, min(1.02, base))
        load = self._unit_load_pct
        load_mw = load * MCR_MW

        # ---- Ramp detection via load slope ----
        prev_load = self._params["steam_flow"].value / 300.0 if self._params["steam_flow"].value else load
        if self._scenario != "Soot Blowing Period":
            if abs(load - prev_load) > 0.03:
                self._set_mode("Ramping")
            elif load < 0.25:
                self._set_mode("Startup")
            elif load < 0.40:
                self._set_mode("Low Load")
            else:
                self._set_mode("Steady State")

        # ---- Scenario / auto event handling ----
        active_scenario = self._scenario
        # If operator selected Normal, auto-fire random deviations occasionally.
        if active_scenario == "Normal Operation":
            if now_mono >= self._auto_event_next and now_mono >= self._auto_event_active_until:
                self._auto_event_current = random.choice([
                    "Excess Air Event",
                    "Under-Air / CO Risk Event",
                    "Drum Level Excursion",
                    "Sensor Data Quality Drop",
                ])
                self._auto_event_active_until = now_mono + random.uniform(40.0, 70.0)
                self._auto_event_next = self._auto_event_active_until + random.uniform(60.0, 120.0)
            if now_mono < self._auto_event_active_until and self._auto_event_current:
                active_scenario = self._auto_event_current
            else:
                self._auto_event_current = None

        # ---- Compute each parameter ----
        scenario_bias = {
            "steam_pressure": 0.0, "steam_temp": 0.0, "steam_flow": 0.0,
            "feedwater_flow": 0.0, "drum_pressure": 0.0, "drum_level": 0.0,
            "furnace_draft": 0.0, "o2": 0.0, "stack_temp": 0.0, "fegt": 0.0,
        }
        invalid_keys: set[str] = set()

        if active_scenario == "Excess Air Event":
            scenario_bias["o2"] = +2.5
            scenario_bias["stack_temp"] = +12
        elif active_scenario == "Under-Air / CO Risk Event":
            scenario_bias["o2"] = -2.2
            scenario_bias["fegt"] = +40
        elif active_scenario == "Drum Level Excursion":
            scenario_bias["drum_level"] = +75
            scenario_bias["drum_pressure"] = -4
        elif active_scenario == "Soot Blowing Period":
            scenario_bias["furnace_draft"] = +2.5
            scenario_bias["stack_temp"] = +8
            scenario_bias["o2"] = +0.6
        elif active_scenario == "Sensor Data Quality Drop":
            invalid_keys.update({"stack_temp", "fegt", "feedwater_flow"})

        for p in PARAMS:
            k = p["key"]
            state = self._params[k]
            expected = p["expected"](load)
            noise_pct = 0.5 if k in ("drum_pressure",) else 1.0
            noise = expected * random.uniform(-noise_pct, noise_pct) / 100.0
            if "amber_abs" in p:
                noise = random.uniform(-p["amber_abs"] * 0.3, p["amber_abs"] * 0.3)
            actual = expected + noise + scenario_bias[k]

            # smoothing toward new value for realism
            if state.value == 0 or seed:
                state.value = actual
            else:
                state.value = state.value * 0.6 + actual * 0.4

            state.expected = expected
            state.valid = k not in invalid_keys
            zone, dev_pct, sub = _classify_zone(p, state.value, expected)
            # safety override: sub-score < 50 -> red
            if sub < 50 and zone == "amber":
                zone = "red"
            state.deviation_pct = dev_pct
            state.zone = zone
            state.sub_score = sub
            state.history.append(round(state.value, 3))
            state.ts_history.append(time.time())
            if state.valid:
                state.day_min = min(state.day_min, state.value)
                state.day_max = max(state.day_max, state.value)
                state.day_sum += state.value
                state.day_count += 1

        # ---- CO simulation (tied to O2 deviation) ----
        o2_state = self._params["o2"]
        o2_target = _expected_o2(load)
        o2_dev = o2_state.value - o2_target
        base_co = 60.0 + random.uniform(-15, 25)
        if o2_dev < -0.5:
            base_co += (abs(o2_dev) ** 2.2) * 180.0  # rises sharply under-air
        if active_scenario == "Under-Air / CO Risk Event":
            base_co += 350.0
        if active_scenario == "Excess Air Event":
            base_co = max(20.0, base_co - 30.0)
        self._co_ppm = max(0.0, self._co_ppm * 0.5 + base_co * 0.5)
        self._co_history.append(round(self._co_ppm, 1))

        # ---- Quadrant classification ----
        if self._co_ppm > 500:
            quadrant = {"id": "CO_CRITICAL", "label": "CO CRITICAL", "color": "red"}
        elif o2_dev >= -0.5 and o2_dev <= 1.5 and self._co_ppm < 200:
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

        # ---- BOI composite score ----
        total_w = 0.0
        weighted = 0.0
        parameter_contrib: list[dict[str, Any]] = []
        any_safety_invalid = False
        for p in PARAMS:
            k = p["key"]
            state = self._params[k]
            w = p["weight"]
            if w == 0:
                continue
            if not state.valid:
                if p["safety"]:
                    any_safety_invalid = True
                continue
            total_w += w
            weighted += w * state.sub_score
            parameter_contrib.append({
                "key": k,
                "name": p["name"],
                "loss": round(w * (100.0 - state.sub_score), 2),
                "weight": w,
                "sub_score": round(state.sub_score, 1),
                "zone": state.zone,
            })

        valid_count = sum(1 for s in self._params.values() if s.valid)
        dq_pct = valid_count / len(PARAMS) * 100.0

        boi = weighted / total_w if total_w > 0 else 0.0
        boi_suppressed = dq_pct < 70.0
        boi_zone = "green" if boi >= 80 else ("amber" if boi >= 65 else "red")

        self._boi_history.append({"ts": time.time(), "boi": round(boi, 1), "load": round(load, 3)})

        # ---- Alerts management ----
        # 1) Per-parameter alerts (skip during Soot Blowing per problem statement)
        suppress = active_scenario == "Soot Blowing Period"
        for p in PARAMS:
            k = p["key"]
            state = self._params[k]
            alert_id = f"param::{k}"
            existing = self._alerts.get(alert_id)
            if not state.valid:
                self._fire_or_update_alert(
                    alert_id, k, p["name"], "amber",
                    "param",
                    f"{p['name']} sensor data invalid",
                    now_mono, suppress,
                )
                continue
            if state.zone == "red":
                self._fire_or_update_alert(
                    alert_id, k, p["name"], "red",
                    "safety" if p["safety"] else "param",
                    f"{p['name']} in RED zone: {state.value:.1f} {p['unit']} (exp {state.expected:.1f})",
                    now_mono, suppress,
                )
            elif state.zone == "amber":
                self._fire_or_update_alert(
                    alert_id, k, p["name"], "amber",
                    "safety" if p["safety"] else "param",
                    f"{p['name']} deviation: {state.value:.1f} {p['unit']} (exp {state.expected:.1f})",
                    now_mono, suppress,
                )
            else:
                self._mark_below_threshold(alert_id, now_mono)

        # 2) Composite BOI alert
        if boi_zone == "red" and not boi_suppressed:
            self._fire_or_update_alert(
                "composite::boi", "boi", "Boiler Operating Index", "red", "composite",
                f"BOI at {boi:.1f} — multiple parameters degraded",
                now_mono, suppress,
            )
        elif boi_zone == "amber" and not boi_suppressed:
            self._fire_or_update_alert(
                "composite::boi", "boi", "Boiler Operating Index", "amber", "composite",
                f"BOI at {boi:.1f} — performance degrading",
                now_mono, suppress,
            )
        else:
            self._mark_below_threshold("composite::boi", now_mono)

        # 3) CO safety
        if self._co_ppm > 500:
            self._fire_or_update_alert(
                "co::critical", "co", "CO Emissions", "red", "co",
                f"CO at {self._co_ppm:.0f} ppm — combustion safety hazard",
                now_mono, False,
            )
        else:
            self._mark_below_threshold("co::critical", now_mono)

        # Auto-clear
        for aid, a in list(self._alerts.items()):
            if a.active and a.below_threshold_since is not None:
                if now_mono - a.below_threshold_since >= self.AUTO_CLEAR_SECONDS:
                    a.active = False
                    a.cleared_ts = _now_iso()

        # Store for snapshot
        self._last_snapshot = {
            "ts": _now_iso(),
            "unit_load_pct": round(load * 100.0, 1),
            "unit_load_mw": round(load_mw, 1),
            "mcr_mw": MCR_MW,
            "mode": self._mode,
            "mode_since": self._mode_since,
            "mode_duration_sec": int(now_mono - self._mode_since_mono),
            "scenario": self._scenario,
            "active_scenario": active_scenario,
            "data_quality_pct": round(dq_pct, 1),
            "safety_data_incomplete": any_safety_invalid,
            "boi": {
                "value": round(boi, 1),
                "zone": boi_zone,
                "suppressed": boi_suppressed,
                "trend": self._boi_trend(),
            },
            "boi_history": list(self._boi_history),
            "parameters": [self._param_payload(p) for p in PARAMS],
            "deviation_waterfall": sorted(parameter_contrib, key=lambda x: -x["loss"]),
            "combustion": {
                "o2_pct": round(o2_state.value, 2),
                "o2_target": round(o2_target, 2),
                "o2_band_low": self._o2_band(load)[0],
                "o2_band_high": self._o2_band(load)[1],
                "excess_air_pct": round(self._excess_air(o2_state.value), 1),
                "co_ppm": round(self._co_ppm, 1),
                "co_history": list(self._co_history),
                "quadrant": quadrant,
                "quadrant_trail": list(self._quadrant_trail),
                "afr_actual": round(self._afr(o2_state.value), 2),
                "afr_design": round(self._afr(o2_target), 2),
                "css": round(self._css(o2_state.value, o2_target, self._co_ppm, quadrant), 1),
                "efficiency": self._efficiency_impact(o2_state.value, o2_target, self._params["stack_temp"].value, load_mw),
                "guidance": self._operator_guidance(o2_state.value, o2_target, self._co_ppm),
            },
            "alerts": self._alert_payload(),
        }

    # ---------- helpers ----------
    def _param_payload(self, p: dict[str, Any]) -> dict[str, Any]:
        state = self._params[p["key"]]
        avg = (state.day_sum / state.day_count) if state.day_count else state.value
        return {
            "key": p["key"],
            "name": p["name"],
            "unit": p["unit"],
            "weight": p["weight"],
            "safety": p["safety"],
            "value": round(state.value, 2),
            "expected": round(state.expected, 2),
            "deviation_pct": round(state.deviation_pct, 2),
            "zone": state.zone,
            "sub_score": round(state.sub_score, 1),
            "valid": state.valid,
            "history": list(state.history),
            "day_min": round(state.day_min, 2) if state.day_count else None,
            "day_max": round(state.day_max, 2) if state.day_count else None,
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

    def _o2_band(self, load: float) -> tuple[float, float]:
        if load >= 0.80:
            return (2.5, 5.5)
        if load >= 0.60:
            return (3.0, 6.0)
        if load >= 0.40:
            return (3.5, 6.5)
        if load >= 0.25:
            return (4.0, 8.0)
        return (5.0, 10.0)

    def _excess_air(self, o2: float) -> float:
        denom = 21.0 - o2
        if denom <= 0.01:
            return 999.9
        return o2 / denom * 100.0

    def _afr(self, o2: float) -> float:
        # illustrative: baseline 7.5 kg-air/kg-fuel at target, scales with EA
        return 7.5 * (1.0 + self._excess_air(o2) / 100.0)

    def _css(self, o2: float, target: float, co: float, quadrant: dict[str, Any]) -> float:
        dev = abs(o2 - target)
        s_o2 = max(0.0, 100.0 - dev * 25.0)
        s_co = max(0.0, 100.0 - (co / 6.0))
        s_q = {"Q1": 100, "Q0": 70, "Q3": 60, "Q2": 20, "Q4": 20, "CO_CRITICAL": 0}[quadrant["id"]]
        return 0.5 * s_o2 + 0.3 * s_co + 0.2 * s_q

    def _efficiency_impact(self, o2: float, target: float, stack_temp: float, load_mw: float) -> dict[str, Any]:
        excess = max(0.0, o2 - target)
        dgl_delta = 0.028 * excess * max(0.0, stack_temp - AMBIENT_TEMP) / (GCV / 1000.0)
        # convert to ₹/hr — steam flow ~= load_mw * 2 t/h approximation, coal ~ steam/6.5
        steam_tph = load_mw * 2.0
        coal_kg_hr = steam_tph * 1000.0 / STEAM_TO_COAL
        avoidable_cost = coal_kg_hr * (dgl_delta / 100.0) * COAL_COST_INR_PER_KG
        return {
            "excess_o2_pct": round(excess, 2),
            "dry_gas_loss_delta_pct": round(dgl_delta, 3),
            "avoidable_cost_inr_per_hr": round(avoidable_cost, 0),
        }

    def _operator_guidance(self, o2: float, target: float, co: float) -> dict[str, str]:
        if co > 500:
            return {"level": "critical", "text": f"CO at {co:.0f} ppm — verify air supply, do NOT reduce further until CO confirmed safe."}
        if o2 < target - 1.0 and co > 300:
            return {"level": "critical", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%), CO at {co:.0f} ppm — increase FD damper cautiously."}
        if o2 > target + 2.0:
            return {"level": "warning", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%). Consider reducing FD damper position to cut dry gas loss."}
        if o2 < target - 0.5:
            return {"level": "warning", "text": f"O₂ at {o2:.1f}% (target {target:.1f}%). Trending under-air — monitor CO closely."}
        return {"level": "ok", "text": f"O₂ at {o2:.1f}% within target band ({target:.1f}%). Combustion trim optimal."}

    def _fire_or_update_alert(
        self, alert_id: str, key: str, name: str, severity: str, kind: str, message: str,
        now_mono: float, suppress: bool,
    ) -> None:
        if suppress:
            self._mark_below_threshold(alert_id, now_mono)
            return
        existing = self._alerts.get(alert_id)
        if existing and existing.active:
            existing.severity = severity
            existing.message = message
            existing.last_update_ts = _now_iso()
            existing.below_threshold_since = None
            return
        # if existed but was cleared, replace
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
        # keep id stable by key for dedup
        self._alerts[alert_id].id = alert_id

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


simulator = BoilerSimulator()
