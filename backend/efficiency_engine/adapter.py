"""
efficiency_engine/adapter.py — PAI-S02 adapter layer.

Builds the typed dataclasses boiler_efficiency.orchestrator.run_energy_balance()
requires from (a) ALREADY-RESOLVED effective values that engine/state_builder.py
computes once per tick and hands in -- never a raw row/tag read of its own --
and (b) the tiered blocked-input placeholders documented in
config/hindalco_boiler9_pai_s02_v1.yaml. Never imports from or modifies
boiler_efficiency/* itself beyond calling its public entry point -- treats
it as a black-box calculation core, per the integration brief's ground rule.

Interconnection fix (see module docstring's "effective values" section in
state_builder.py): this module used to read module1_features.csv's row and
its own FW_PR_TO_FCS row directly, independently of PAI-S01's scoring and
PAI-S03's scenario logic -- meaning PAI-S02 could show a different O2 (during
Under-Air scenarios) or an unflagged feedwater_flow (during Sensor Data
Quality Drop) than PAI-S01/S03 were showing for the SAME tag at the SAME
tick. Fixed by having state_builder.py resolve every shared tag ONCE
(PAI-S01's scoring + any active scenario's effect) and pass the resolved
value + its data_source in, rather than this module re-reading anything raw.

Every blocked/placeholder field is drawn from the library's own bundled
ASME Appendix D-4 reference coal
(efficiency_engine/examples/mundra_appendix_d4.json) -- a self-consistent,
already-validated composition (see tests/test_appendix_d4.py), NOT a guess
and NOT this plant's actual coal. Each placeholder's data_source is tagged
"simulated" (never "real") in run_efficiency()'s returned data_source map,
so a consumer can never mistake it for a measured value -- same discipline
as Module 1/2's data_source convention.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .boiler_efficiency.models import (
    FuelAnalysis,
    RefuseAnalysis,
    AmbientConditions,
    GasMeasurements,
    EnthalpyInputs,
    EfficiencyAssumptions,
    BoilerDutyInputs,
    GCVCheckInputs,
)
from .boiler_efficiency.orchestrator import run_energy_balance

logger = logging.getLogger(__name__)

_REFERENCE_COAL_PATH = Path(__file__).parent / "examples" / "mundra_appendix_d4.json"
_REFERENCE_COAL: dict[str, Any] = json.loads(_REFERENCE_COAL_PATH.read_text())

# config/hindalco_boiler9_pai_s01_v2.yaml COAL_GCV -- real plant value,
# Proximate Analysis basis. Only real fuel constant in the repo (see
# hindalco_boiler9_pai_s02_v1.yaml fuel.* block for the full correction note
# on why oxygen_pct/nitrogen_pct/sulfur_pct are NOT similarly available).
GCV_KCAL_PER_KG = 3610.0
GCV_KJ_PER_KG = GCV_KCAL_PER_KG * 4.1868

# static_config placeholders -- see hindalco_boiler9_pai_s02_v1.yaml gas.* /
# enthalpy.* blocks for sourcing notes.
FLUE_GAS_CPG_BTU_LBM_F = 0.264
REFERENCE_WATER_TEMP_C = 25.0

# GCV Check band -- exposed as module constants (not just inline literals)
# so state_builder.py's GCV WARN alert message can cite the exact configured
# band without duplicating the numbers.
GCV_CHECK_LOWER = 0.95
GCV_CHECK_UPPER = 1.04

# The six BoilerDutyInputs fields this module needs resolved effective
# values for -- see run_efficiency()'s boiler_duty_fields parameter.
BOILER_DUTY_FIELDS = (
    "MAIN_STEAM_FLOW", "MAIN_STEAM_PRESSURE", "MAIN_STEAM_TEMPERATURE",
    "FEEDWATER_FLOW", "FW_PR_TO_FCS", "FEEDWATER_TEMP_TO_FCS",
)

# ---- Spec Gate: GCV staleness (spec: GCV must be fresher than 8 hours or
# efficiency is marked "GCV Data Stale"). No real per-shift lab-entry
# mechanism exists yet -- GCV_LAST_UPDATED is set once, at process start,
# as the honest placeholder ("now" until a real update mechanism exists,
# per the brief). This means the gate will not trigger during any single
# server run under 8 hours -- expected, not a bug -- but the check itself
# is real and independently testable (see tests exercising gcv_is_stale()
# with an injected `now`). ----
GCV_LAST_UPDATED: datetime = datetime.now(timezone.utc)
GCV_MAX_AGE_HOURS = 8.0


def gcv_age_hours(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - GCV_LAST_UPDATED).total_seconds() / 3600.0


def gcv_is_stale(now: datetime | None = None) -> bool:
    return gcv_age_hours(now) > GCV_MAX_AGE_HOURS


# ---- Spec Gate: Direct-vs-indirect mass-balance cross-check (spec:
# |eta_direct - eta_indirect| > 2% -> "Mass Balance Discrepancy - Check
# Flow Meters"). eta_indirect is the library's own heat-loss-method result
# (efficiency.values.boiler_efficiency_hhv_pct). eta_direct is NOT exposed
# by the library and CANNOT be derived from its output: fuel_firing's
# fuel_heat_input_mw is itself back-calculated FROM eta_indirect
# (m07_firing.py: fuel_kg_s = boiler_duty_mw / (hhv_kj_kg * efficiency_pct
# / 100), where efficiency_pct IS eta_indirect) -- treating that as
# "eta_direct" would be circular, not an independent cross-check, verified
# numerically (fuel_heat_input_mw == boiler_duty_mw / (eta_indirect/100)
# to float precision on live data). A genuinely independent eta_direct
# instead uses the real "FUEL FLOW" historian tag (already used by Module 2
# for afr_actual) as Q_input, computed here in the adapter -- an adapter/
# config addition, not a library-internals change. ----
MASS_BALANCE_THRESHOLD_PCT = 2.0


def compute_eta_direct_pct(boiler_duty_mw: float, fuel_flow_tph: float, gcv_kj_per_kg: float) -> float | None:
    if fuel_flow_tph is None or fuel_flow_tph <= 0:
        return None
    fuel_kg_s = fuel_flow_tph * 1000.0 / 3600.0
    q_input_mw = fuel_kg_s * gcv_kj_per_kg / 1000.0
    if q_input_mw <= 0:
        return None
    return boiler_duty_mw / q_input_mw * 100.0


# ---- Spec: Efficiency Gauge zone thresholds (Phase B of the PAI-S02 Spec
# Alignment brief) -- see config/hindalco_boiler9_pai_s02_v1.yaml scoring.*
# for the full sourcing note, including the checked (not assumed)
# relationship between eta_design_pct and the Appendix D-4 corrected
# efficiency this repo already computes. eta_design_pct and
# eta_guaranteed_pct are deliberately two separate constants -- only
# eta_design_pct feeds the deviation formula; eta_guaranteed_pct is stored
# for a possible future use, not wired into any zone/alert logic yet. ----
ETA_DESIGN_PCT = 87.71
ETA_GUARANTEED_PCT = 86.0
ETA_DEVIATION_GREEN_MAX_PCT = 1.0
ETA_DEVIATION_AMBER_MAX_PCT = 2.5

# CO > 300 ppm -> RED "Incomplete Combustion" flag. Threshold is spec-given;
# the CO reading it compares against is the combustion module's simulated
# co_ppm (no real tag confirmed yet -- see decisions.md #17), so this flag
# is computed/shown (data_source "simulated") but deliberately does NOT
# drive the main gauge zone color, which stays real-data-driven off
# eta_deviation alone.
CO_INCOMPLETE_COMBUSTION_PPM = 300.0


def classify_efficiency_zone(eta_actual_pct: float) -> dict[str, Any]:
    """eta_deviation = eta_design - eta_actual (spec). GREEN <= 1.0pt,
    AMBER 1.0-2.5pt, RED > 2.5pt below design. A negative deviation
    (actual efficiency exceeds design) is GREEN -- the formula and bands
    handle over-performance without a separate case."""
    deviation_pct = ETA_DESIGN_PCT - eta_actual_pct
    if deviation_pct <= ETA_DEVIATION_GREEN_MAX_PCT:
        zone = "green"
    elif deviation_pct <= ETA_DEVIATION_AMBER_MAX_PCT:
        zone = "amber"
    else:
        zone = "red"
    return {
        "eta_actual_hhv_pct": eta_actual_pct,
        "eta_design_pct": ETA_DESIGN_PCT,
        "eta_guaranteed_pct": ETA_GUARANTEED_PCT,
        "eta_deviation_pct": deviation_pct,
        "zone": zone,
        "green_max_pct": ETA_DEVIATION_GREEN_MAX_PCT,
        "amber_max_pct": ETA_DEVIATION_AMBER_MAX_PCT,
    }


def classify_co_flag(co_ppm: float | None, co_data_source: str = "simulated") -> dict[str, Any]:
    triggered = co_ppm is not None and co_ppm > CO_INCOMPLETE_COMBUSTION_PPM
    return {
        "co_ppm": co_ppm,
        "setpoint_ppm": CO_INCOMPLETE_COMBUSTION_PPM,
        "triggered": triggered,
        "label": "Incomplete Combustion" if triggered else None,
        "data_source": co_data_source,
    }


def _placeholder_fuel_composition() -> dict[str, float]:
    """Ultimate + proximate analysis fields with no real plant source yet
    (hindalco_boiler9_pai_s02_v1.yaml fuel.* block) -- borrowed unmodified
    from the library's own bundled reference coal."""
    f = _REFERENCE_COAL["fuel"]
    return {
        "carbon_pct": f["carbon_pct"],
        "hydrogen_pct": f["hydrogen_pct"],
        "oxygen_pct": f["oxygen_pct"],
        "nitrogen_pct": f["nitrogen_pct"],
        "sulfur_pct": f["sulfur_pct"],
        "ash_pct": f["ash_pct"],
        "moisture_pct": f["moisture_pct"],
        "volatile_matter_pct": f["volatile_matter_pct"],
        "fixed_carbon_pct": f["fixed_carbon_pct"],
    }


def build_inputs(
    boiler_duty_fields: dict[str, tuple[float | None, str]],
    o2_value: float,
    o2_data_source: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """Returns (kwargs-by-dataclass-name, data_source map, assumption_notes).

    `boiler_duty_fields` maps each of BOILER_DUTY_FIELDS to
    (resolved_value, data_source) -- already resolved by state_builder.py
    against PAI-S01's own ParamResult/stale-detection for the four tags it
    shares (MAIN_STEAM_FLOW/PRESSURE/TEMPERATURE, FEEDWATER_FLOW) and this
    module's own stale tracker for the two it doesn't (FW_PR_TO_FCS,
    FEEDWATER_TEMP_TO_FCS). `o2_value`/`o2_data_source` are likewise
    PAI-S03's fully-resolved O2 (post scenario bias, if any active) -- see
    this module's docstring. Caller (run_efficiency) guarantees every value
    here is non-None; a None anywhere short-circuits to a data_gap response
    before this function is called.

    data_source values match the vocabulary already in production use on
    /api/state (Module 1/2's state_builder.py + frontend DataSourceChip):
    "real", "stale", "simulated", "static_config". assumption_notes carries
    the longer prose explanations (e.g. the O2 tap-location assumption
    below) that don't fit a one-word chip, for the frontend's Data Source /
    Assumptions panel."""

    data_source: dict[str, str] = {}
    assumption_notes: list[str] = []

    placeholder_fuel = _placeholder_fuel_composition()
    fuel_kwargs = {
        **placeholder_fuel,
        "hhv_kj_kg": GCV_KJ_PER_KG,
        "name": "Hindalco Boiler-9 coal (placeholder ultimate/proximate analysis)",
    }
    for k in placeholder_fuel:
        data_source[f"fuel.{k}"] = "simulated"
    # Gate: GCV staleness (spec, >8h -> "GCV Data Stale"). GCV_LAST_UPDATED
    # is process-start time (no real per-shift entry mechanism exists yet,
    # see GCV_LAST_UPDATED's own comment) -- won't trigger within one
    # server run, but the check is real and independently testable.
    gcv_stale = gcv_is_stale()
    data_source["fuel.hhv_kj_kg"] = "stale" if gcv_stale else "real"
    assumption_notes.append(
        "fuel.* (except hhv_kj_kg): full Ultimate + Proximate Analysis not yet "
        "available for this plant's coal -- using the calculation library's own "
        "bundled ASME Appendix D-4 reference coal composition as a clearly-"
        "flagged placeholder, NOT this plant's actual coal. Blocked on the same "
        "lab report as Module 2 (PAI-S03)'s afr_design."
    )

    refuse_kwargs = dict(_REFERENCE_COAL["refuse"])
    for k in refuse_kwargs:
        data_source[f"refuse.{k}"] = "simulated"
    assumption_notes.append(
        "refuse.*: ash distribution / unburned-carbon / ash-temperature data is "
        "an entirely new plant-input category, not yet supplied -- using the "
        "reference coal's refuse block as a placeholder (ash distribution must "
        "sum to 100%, a hard library requirement)."
    )

    ambient_kwargs = dict(_REFERENCE_COAL["ambient"])
    for k in ambient_kwargs:
        data_source[f"ambient.{k}"] = "simulated"
    assumption_notes.append(
        "ambient.*: plant weather data (dry bulb, pressure, RH) is not in the "
        "historian export -- using the reference coal example's ambient block "
        "as a placeholder pending an external weather source or plant assumption."
    )

    # o2_economizer_outlet_dry_pct: the one real value in this whole block.
    # Module 1's only real O2 tag is physically at the air-heater flue-gas
    # INLET (FLUE_GAS_O2_APH_INLET) which, in this plant's single-
    # economizer-stage gas path, is the same position as "economizer
    # outlet" -- a documented assumption, not silently reused for BOTH O2
    # fields (see config note). o2_air_heater_outlet_dry_pct has no real
    # candidate at all -- stays a placeholder. o2_value/o2_data_source are
    # PAI-S03's own fully-resolved O2 (post scenario bias/stale-flagging if
    # any), passed in by state_builder.py -- NOT re-read here, so PAI-S02
    # can never show a different O2 than PAI-S03 for the same tick.
    gas_ref = _REFERENCE_COAL["gas"]
    gas_kwargs = {
        "o2_economizer_outlet_dry_pct": o2_value,
        "o2_air_heater_outlet_dry_pct": gas_ref["o2_air_heater_outlet_dry_pct"],
        "flue_gas_specific_heat_cpg_btu_lbm_f": FLUE_GAS_CPG_BTU_LBM_F,
        "gas_temp_air_heater_inlet_c": gas_ref["gas_temp_air_heater_inlet_c"],
        "gas_temp_air_heater_outlet_c": gas_ref["gas_temp_air_heater_outlet_c"],
        "air_temp_air_heater_inlet_c": gas_ref["air_temp_air_heater_inlet_c"],
        "air_temp_fan_inlet_c": gas_ref.get("air_temp_fan_inlet_c"),
    }
    data_source["gas.o2_economizer_outlet_dry_pct"] = o2_data_source
    data_source["gas.o2_air_heater_outlet_dry_pct"] = "simulated"
    data_source["gas.flue_gas_specific_heat_cpg_btu_lbm_f"] = "static_config"
    data_source["gas.gas_temp_air_heater_inlet_c"] = "simulated"
    data_source["gas.gas_temp_air_heater_outlet_c"] = "simulated"
    data_source["gas.air_temp_air_heater_inlet_c"] = "simulated"
    data_source["gas.air_temp_fan_inlet_c"] = "simulated"
    assumption_notes.append(
        "gas.o2_economizer_outlet_dry_pct is REAL (or simulated/stale, matching "
        "whatever PAI-S03's Combustion Monitor is showing this same tick -- see "
        "data_source above) under a documented physical-location assumption: "
        "this plant's only O2 tag (FLUE_GAS_O2_APH_INLET) is physically at the "
        "air-heater INLET, which in this plant's single-economizer-stage gas "
        "path is the same position as \"economizer outlet\" -- mapped here "
        "deliberately, NOT reused for the AH-outlet field too (that field, and "
        "air_heater_leakage_pct downstream of it, stay placeholder-driven)."
    )
    assumption_notes.append(
        "gas.gas_temp_air_heater_inlet_c/_outlet_c and air_temp_air_heater_inlet_c: "
        "no tag explicitly named \"air heater\" exists in the historian. Candidate "
        "tags exist nearby (economizer/ESP gas-temp tags; AIR TEMP AT AIR BOX "
        "A/B for air-side, though that reads as post-air-heater, the wrong side) "
        "but none confirmed -- needs plant/Punarbasu confirmation before mapping."
    )

    enthalpy_kwargs = {"reference_water_temperature_c": REFERENCE_WATER_TEMP_C}
    data_source["enthalpy.reference_water_temperature_c"] = "static_config"

    # EfficiencyAssumptions() library defaults used as-is -- Awes's own
    # values baked into models.py, not invented here (see config note).
    assumptions_kwargs: dict[str, Any] = {}
    for k in (
        "surface_radiation_loss_pct", "other_loss_pct", "auxiliary_power_credit_pct",
        "additional_moisture_kg_kg_fuel", "hydrogen_to_water_factor",
        "unburned_carbon_heating_value_kj_kg", "spent_sorbent_lbm_per_100_lbm_fuel",
    ):
        data_source[f"assumptions.{k}"] = "static_config"
    assumption_notes.append(
        "assumptions.* (surface_radiation_loss_pct, other_loss_pct, etc.): using "
        "the calculation library's own built-in defaults (Awes's values, baked "
        "into models.py) pending an explicit plant-specific override."
    )

    # Already-resolved by state_builder.py: MAIN_STEAM_FLOW/PRESSURE/
    # TEMPERATURE and FEEDWATER_FLOW come from PAI-S01's own ParamResult for
    # that tag (so a sensor-drop-invalidated or stale feedwater_flow reads
    # the same way here as it does on the Parameter Grid); FW_PR_TO_FCS and
    # FEEDWATER_TEMP_TO_FCS come from this module's own stale tracker (no
    # PAI-S01 equivalent exists for those two).
    boiler_duty_kwargs = {k: v for k, (v, _ds) in boiler_duty_fields.items()}
    for k, (_v, ds) in boiler_duty_fields.items():
        data_source[f"boiler_duty.{k}"] = ds

    gcv_check_kwargs = {"lower": GCV_CHECK_LOWER, "upper": GCV_CHECK_UPPER, "apply_correction": False}
    for k in gcv_check_kwargs:
        data_source[f"gcv_check.{k}"] = "static_config"

    return (
        {
            "fuel": fuel_kwargs,
            "refuse": refuse_kwargs,
            "ambient": ambient_kwargs,
            "gas": gas_kwargs,
            "enthalpy": enthalpy_kwargs,
            "assumptions": assumptions_kwargs,
            "boiler_duty": boiler_duty_kwargs,
            "gcv_check": gcv_check_kwargs,
        },
        data_source,
        assumption_notes,
    )


def run_efficiency(
    boiler_duty_fields: dict[str, tuple[float | None, str]],
    o2_value: float | None,
    o2_data_source: str,
    stack_temp_data_source: str = "real",
    fuel_flow_tph: float | None = None,
    fuel_flow_data_source: str = "real",
    co_ppm: float | None = None,
    co_data_source: str = "simulated",
) -> dict[str, Any]:
    """Builds inputs, runs the unmodified orchestrator, and returns the API
    payload: full engine output + data_source map + warnings (the library's
    own validate_fuel() warnings are surfaced directly, never discarded).

    Takes only already-resolved values -- see build_inputs()'s docstring and
    this module's own docstring for why (single source of truth per tag,
    shared with PAI-S01/S03, not an independent raw read).

    A None anywhere (a shared tag invalidated by a scenario this tick, e.g.
    Sensor Data Quality Drop on feedwater_flow, or a genuinely missing raw
    reading) short-circuits to an explicit data-gap status. Real replay data
    also occasionally hits combinations the library's own engineering
    guards correctly reject (e.g. near-zero flow during a startup/shutdown
    transient making calculated boiler duty <= 0, or a CoolProp
    property-table domain error at an extreme pressure/temperature pair) --
    caught here and returned as an explicit error status rather than
    crashing the replay tick, same spirit as Module 1's
    safety_data_incomplete gap-handling.

    Gate (spec): Stack Temp or O2 INVALID -> Dry Gas Loss (and therefore
    overall efficiency, since DGL feeds total_heat_loss_pct) cannot be
    calculated. `stack_temp_data_source` is PAI-S01's own real
    STACK_TEMPERATURE ParamResult's data_source -- Stack Temp is NOT yet a
    live numeric input to DGL itself (gas_temp_air_heater_outlet_c is still
    a placeholder, see config's gas.* note), so this gates on the best
    currently-available real proxy for "is flue-gas temperature
    instrumentation trustworthy right now," not literally the DGL formula's
    own input; once a real air-heater-outlet gas temp tag is confirmed,
    this gate will apply directly to the same tag driving the calculation.
    Only "stale" blocks (frozen/untrustworthy) -- "simulated" (an active
    demo scenario deliberately biasing a value) is not treated as invalid.
    """
    missing = [k for k, (v, _ds) in boiler_duty_fields.items() if v is None]
    if o2_value is None:
        missing.append("o2 (FLUE_GAS_O2_APH_INLET)")
    if missing:
        return {
            "status": "data_gap",
            "error": f"Required real tag(s) missing/invalid this tick: {', '.join(missing)}",
            "data_source": {},
            "assumption_notes": [],
            "warnings": [],
        }

    invalid = []
    if o2_data_source == "stale":
        invalid.append("O2 (FLUE_GAS_O2_APH_INLET)")
    if stack_temp_data_source == "stale":
        invalid.append("Stack Temperature")
    if invalid:
        return {
            "status": "invalid_inputs",
            "error": f"Dry Gas Loss cannot be calculated -- invalid/frozen input(s): {', '.join(invalid)}",
            "data_source": {},
            "assumption_notes": [],
            "warnings": [],
        }

    kwargs, data_source, assumption_notes = build_inputs(boiler_duty_fields, o2_value, o2_data_source)
    try:
        result = run_energy_balance(
            FuelAnalysis(**kwargs["fuel"]),
            RefuseAnalysis(**kwargs["refuse"]),
            AmbientConditions(**kwargs["ambient"]),
            GasMeasurements(**kwargs["gas"]),
            EnthalpyInputs(**kwargs["enthalpy"]),
            EfficiencyAssumptions(**kwargs["assumptions"]),
            BoilerDutyInputs(**kwargs["boiler_duty"]),
            GCVCheckInputs(**kwargs["gcv_check"]),
        )
    except Exception as e:  # library's own engineering guards (ValueError) or
        # a CoolProp domain error -- surface plainly, don't crash the tick.
        logger.warning("efficiency_engine calculation failed this row: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data_source": data_source,
            "assumption_notes": assumption_notes,
            "warnings": [],
        }

    # ---- Gate: direct-vs-indirect mass-balance cross-check (spec) --
    # see this module's docstring above for why eta_direct cannot come
    # from the library's own output (circular via fuel_firing) and instead
    # uses the real FUEL FLOW historian tag as an independent Q_input. ----
    eta_indirect = result["efficiency"]["values"]["boiler_efficiency_hhv_pct"]
    boiler_duty_mw = result["boiler_duty"]["values"]["boiler_duty_mw"]
    eta_direct = compute_eta_direct_pct(boiler_duty_mw, fuel_flow_tph, GCV_KJ_PER_KG)
    if eta_direct is not None:
        deviation_pct = eta_direct - eta_indirect
        mass_balance_discrepancy = abs(deviation_pct) > MASS_BALANCE_THRESHOLD_PCT
        result["direct_method"] = {
            "eta_direct_hhv_pct": eta_direct,
            "eta_indirect_hhv_pct": eta_indirect,
            "deviation_pct": deviation_pct,
            "threshold_pct": MASS_BALANCE_THRESHOLD_PCT,
            "mass_balance_discrepancy": mass_balance_discrepancy,
        }
        data_source["direct_method.eta_direct_hhv_pct"] = fuel_flow_data_source
        assumption_notes.append(
            "direct_method.eta_direct_hhv_pct: computed from the real \"FUEL FLOW\" "
            "historian tag (independent of the library's own fuel_firing output, "
            "which is circular -- see this module's docstring) x the real plant "
            "GCV. Currently disagrees with eta_indirect frequently (not rare), "
            "because eta_indirect's loss terms still run on a placeholder fuel "
            "composition (see fuel.* note) that barely varies with real "
            "conditions, while eta_direct moves with real Fuel Flow and real "
            "steam-side heat balance -- this cross-check becomes fully meaningful "
            "once real Ultimate/Proximate Analysis replaces the placeholder."
        )
    else:
        result["direct_method"] = {
            "eta_direct_hhv_pct": None, "eta_indirect_hhv_pct": eta_indirect,
            "deviation_pct": None, "threshold_pct": MASS_BALANCE_THRESHOLD_PCT,
            "mass_balance_discrepancy": False,
        }
        data_source["direct_method.eta_direct_hhv_pct"] = "unavailable"

    # ---- Gate: GCV staleness surfaced at top level too (spec: mark
    # efficiency "GCV Data Stale"), not just buried in the fuel.hhv_kj_kg
    # data_source entry. ----
    result["gcv_freshness"] = {
        "last_updated": GCV_LAST_UPDATED.isoformat(),
        "age_hours": round(gcv_age_hours(), 3),
        "max_age_hours": GCV_MAX_AGE_HOURS,
        "stale": gcv_is_stale(),
    }

    # ---- Spec: Efficiency Gauge zone (Phase B) -- real-data-driven off
    # eta_indirect (the same "HHV Efficiency" headline figure already
    # displayed) vs. the plant-provided eta_design_pct. The CO flag is
    # computed alongside it but kept structurally separate (see
    # classify_co_flag()'s docstring) so a simulated CO reading can never
    # flip the real-data-driven gauge color. DGL/Fly-Ash setpoint flags are
    # NOT computed here -- no numeric setpoint exists (scoring.yaml
    # excess_dgl_setpoint/excess_fly_ash_setpoint are null pending
    # Punarbasu/Awes input), so leaving them out is the accurate state, not
    # an oversight. ----
    result["zone"] = classify_efficiency_zone(eta_indirect)
    result["zone"]["flags"] = {
        "co_incomplete_combustion": classify_co_flag(co_ppm, co_data_source),
        "excess_dry_gas_loss": {"status": "pending", "reason": "setpoint not given in spec -- Punarbasu/Awes ask"},
        "excess_unburnt_carbon": {"status": "pending", "reason": "setpoint not given in spec -- Punarbasu/Awes ask"},
    }

    # ---- Phase C: CO Loss -- confirmed (grepped the entire boiler_efficiency
    # package) that NO CO-loss formula exists anywhere in the library, at any
    # level. This is architecturally different from a blocked/stale REAL
    # value (the other data_source states) -- there is no calculation to be
    # blocked, so it gets its own status, "unavailable_no_formula", rather
    # than "simulated"/"stale". Deliberately NOT folded into total_heat_loss_pct
    # or any bar's numeric value -- inventing a number here would silently
    # change a figure that's supposed to be Awes's library output, untouched.
    # See decisions.md for the Phase C reconciliation and the Awes ask this
    # generated (should the library be extended to compute this, given CO
    # Loss is a named spec component?). ----
    result["co_loss"] = {
        "value": None,
        "data_source": "unavailable_no_formula",
        "label": "CO Loss",
        "message": "CO Loss — not computed (no formula exists in the calculation engine)",
    }
    data_source["efficiency.co_loss_pct"] = "unavailable_no_formula"

    # ---- Phase D: Data Quality composite badge -- rolls up GCV freshness +
    # O2 validity into one summary indicator (spec: "a single composite
    # badge"), on top of (not replacing) the existing per-field
    # DataSourceChips. Fly-ash data has no timestamp to compute an "age"
    # from at all (every refuse/ash field is the bundled reference-coal
    # placeholder, static_config, not a live tag) -- shown as its own static
    # line rather than invented as a numeric age, and does NOT drive the
    # composite color since it's a permanent, already-documented gap, not a
    # moment-to-moment data-quality signal. Gate 3 already blocks
    # (status: "invalid_inputs") before this point whenever O2/Stack Temp go
    # stale, so by the time control reaches here O2 is only ever "real" or
    # "simulated" (an active demo scenario), never "stale". ----
    result["data_quality"] = {
        "gcv_fresh": not gcv_is_stale(),
        "o2_data_source": o2_data_source,
        "fly_ash_data_source": "static_config",
        "composite": "good" if (not gcv_is_stale() and o2_data_source == "real") else "degraded",
    }

    result["status"] = "ok"
    result["data_source"] = data_source
    result["assumption_notes"] = assumption_notes
    return result
