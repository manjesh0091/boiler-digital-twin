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

As of 2026-08-13, fuel.* (Ultimate + Proximate Analysis), refuse.*
ash-split (distribution/unburned-carbon, NOT temperatures), and ambient.*
are real static values from a plant engineering document (data_source
"static_config", see PLANT_ENGINEERING_DOC_DATE below) -- no longer the
library's bundled placeholder. Every STILL-blocked field (refuse.*
ash temperatures, gas.* air-heater tags, etc.) continues to draw from the
library's own bundled ASME Appendix D-4 reference coal
(efficiency_engine/examples/mundra_appendix_d4.json) -- a self-consistent,
already-validated composition (see tests/test_appendix_d4.py), NOT a guess
and NOT this plant's actual coal. Each still-blocked field's data_source is
tagged "simulated" (never "real") in run_efficiency()'s returned
data_source map, so a consumer can never mistake it for a measured value --
same discipline as Module 1/2's data_source convention.
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
# Proximate Analysis basis, used ONLY for Gate 1's independent eta_direct
# Q_input (compute_eta_direct_pct() below) -- deliberately NOT reconciled
# with fuel.hhv_kj_kg's own, separately-sourced value below (~1.6% apart;
# see FUEL_ULTIMATE_PROXIMATE's docstring note) so Gate 1 keeps an
# independent GCV source on each side of its cross-check, not the same
# document feeding both.
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

# ---- RESOLVED 2026-08-13 (ask-list items #14/#15/#16): real static values
# from a plant engineering document (fuel ultimate/proximate analysis
# report), superseding the library's bundled Appendix D-4 reference-coal
# placeholder for these three blocks. See
# hindalco_boiler9_pai_s02_v1.yaml's fuel.*/refuse.*/ambient.* sections for
# the full per-field sourcing notes (including the fuel.hhv_kj_kg vs.
# GCV_KCAL_PER_KG discrepancy note above).
#
# Unlike GCV_LAST_UPDATED below (which re-evaluates to "now" every process
# start, an acknowledged placeholder for a real per-shift lab-entry
# mechanism that doesn't exist yet -- decisions.md #30), this is a fixed
# date: these are periodic test-report values, not per-shift entries, so
# "now" at every restart would be actively wrong, not just imprecise.
# Update PLANT_ENGINEERING_DOC_DATE by hand when the plant supplies a new
# test report. ----
PLANT_ENGINEERING_DOC_DATE: datetime = datetime(2026, 8, 13, tzinfo=timezone.utc)


def plant_doc_age_days(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - PLANT_ENGINEERING_DOC_DATE).total_seconds() / 86400.0


# Ultimate + Proximate Analysis (fuel.* in the config). Ultimate-analysis
# closure (C+H+O+N+S+ash+moisture) = 100.01%, well inside the library's own
# validate_fuel() tolerance (raises past 1.0%, warns past 0.1%). VM+FC+ash+
# moisture sums to 106.0%, not 100% -- proximate analyses are commonly
# reported on a different moisture basis than the ultimate analysis in real
# lab reports, and the library doesn't validate this pair at all, so this
# isn't a blocking concern -- noted for transparency only.
FUEL_ULTIMATE_PROXIMATE = {
    "carbon_pct": 36.13,
    "hydrogen_pct": 2.05,
    "oxygen_pct": 11.32,
    "nitrogen_pct": 0.89,
    "sulfur_pct": 0.5,
    "ash_pct": 36.81,
    "moisture_pct": 12.31,
    "volatile_matter_pct": 26.4,
    "fixed_carbon_pct": 30.48,
}
FUEL_HHV_KJ_KG = 14870.0
# kcal/kg form -- the actual GCV feeding every efficiency figure Awes's
# library computes (eta_indirect, all loss terms), unlike GCV_KCAL_PER_KG
# above (Gate 1's deliberately-independent Q_input source, never used
# inside the library itself). Any display meant to represent "the GCV
# behind these efficiency numbers" should use THIS constant, not
# GCV_KCAL_PER_KG.
FUEL_HHV_KCAL_KG = FUEL_HHV_KJ_KG / 4.1868

# Ash split (refuse.* distribution_pct + unburned_carbon_pct only --
# temperatures are still NOT in this document, see config note). Bed +
# cyclone + APH + ESP distribution sums to exactly 100%, the library's own
# hard requirement.
REFUSE_ASH_SPLIT = {
    "bed_ash_distribution_pct": 10.0,
    "cyclone_ash_distribution_pct": 40.0,
    "aph_ash_distribution_pct": 0.0,
    "esp_ash_distribution_pct": 50.0,
    "bed_ash_unburned_carbon_pct": 6.4,
    "cyclone_ash_unburned_carbon_pct": 0.3,
    "aph_ash_unburned_carbon_pct": 0.0,
    "esp_ash_unburned_carbon_pct": 2.31,
}

# ambient.* -- static design-basis figures, not a live tag (still not in
# the historian export).
AMBIENT_CONDITIONS = {
    "dry_bulb_c": 37.8,
    "pressure_bar_a": 0.9888,
    "relative_humidity_pct": 46.61,
    "fuel_temp_c": 37.8,
}

# =============================================================================
# Logical Filtering & Validation Rules (plant engineering document,
# 2026-08-13) -- 14 rules applied before/alongside feeding values into the
# efficiency calculation engine. Same Gate-style pattern as Phase A's Gates
# 1-3: rules 1 and 2 are real BLOCKING gates (their spec'd action is "do not
# proceed" / normalize-or-flag a data-entry error) evaluated in
# run_efficiency() before the library is even called; every other rule is
# advisory, returned in result["validation_checks"] without blocking
# anything. Rule 3 is not implemented here at all -- it IS the existing GCV
# Check mechanism (gcv_check.values, Phase A Gate 2's sibling), cross-
# referenced from the library's own output rather than recomputed.
#
# Several rules can only run against CURRENTLY-PLACEHOLDER inputs (rule 4's
# AH-outlet O2, rule 8's bed-ash temperature) or a structurally-incomplete
# subset of what the rule literally asks for (rule 5's gas-path chain --
# furnace/SH/APH-outlet/ESP-outlet gas temps have no confirmed real tag).
# These return status "not_checkable" rather than a fabricated pass/fail,
# with the specific gap named in the message -- never silently treated as
# passing. Rule 10 (ambient data currency) is not programmatically
# checkable at all with this system's current data shape (no distinct
# "test window timestamp" separate from the document's own date) and always
# returns "not_checkable" -- a flag for manual confirmation, not a gate.
# =============================================================================

RULE_MASS_CLOSURE_TOLERANCE_PCT = 0.5
RULE_ASH_SPLIT_EPSILON_PCT = 0.01
RULE_O2_RISE_TYPICAL_MIN_PP = 0.3
RULE_O2_RISE_TYPICAL_MAX_PP = 1.5
RULE_O2_RISE_FLAG_PP = 2.0
RULE_AB_DEVIATION_MAX_PCT = 5.0
# Rule 7's own doc text says "within +/- 3-5%", a range not a single number
# -- using the lenient/outer bound (5%) as the hard tolerance so this
# doesn't false-flag on the low end of the stated range; the ambiguity is
# named in the check's own message, not silently resolved.
RULE_FEEDWATER_STEAM_BALANCE_TOLERANCE_PCT = 5.0
RULE_BED_ASH_INBED_RANGE_C = (850.0, 950.0)
RULE_BED_ASH_POSTCOOLER_RANGE_C = (150.0, 250.0)
RULE_ASME_HYDROGEN_TO_WATER_FACTOR = 8.937
RULE_ASME_UBC_HEATING_VALUE_KJ_KG = 33700.0
RULE_MAIN_STEAM_PRESSURE_MAX_KG_CM2 = 92.0
RULE_MAIN_STEAM_TEMPERATURE_MAX_C = 540.0
RULE_LOAD_STABILITY_TOLERANCE_PCT = 2.0
# Rule 14's doc text says "30-60 minutes" -- using the stricter/longer end
# (60 min = 12 rows at this dataset's 5-min interval), same convention this
# project already uses for TRAINING_STALE_STREAK_ROWS (shared/data_quality.py).
RULE_LOAD_STABILITY_WINDOW_ROWS = 12


def check_mass_closure(fuel_kwargs: dict[str, Any]) -> dict[str, Any]:
    total = sum(fuel_kwargs[k] for k in (
        "carbon_pct", "hydrogen_pct", "oxygen_pct", "nitrogen_pct",
        "sulfur_pct", "ash_pct", "moisture_pct",
    ))
    error = total - 100.0
    ok = abs(error) <= RULE_MASS_CLOSURE_TOLERANCE_PCT
    return {
        "rule": 1, "name": "Ultimate + Proximate mass closure",
        "status": "pass" if ok else "fail",
        "message": (
            f"C+H+O+N+S+Ash+Moisture = {total:.2f}% "
            f"(tolerance 100% +/-{RULE_MASS_CLOSURE_TOLERANCE_PCT}%)"
            + ("" if ok else " -- OUT OF TOLERANCE, request a corrected lab sheet, do not proceed.")
        ),
        "applies_to": "fuel.*",
    }


def check_ash_split_closure(refuse_kwargs: dict[str, Any]) -> dict[str, Any]:
    total = sum(refuse_kwargs[k] for k in (
        "bed_ash_distribution_pct", "cyclone_ash_distribution_pct",
        "aph_ash_distribution_pct", "esp_ash_distribution_pct",
    ))
    ok = abs(total - 100.0) <= RULE_ASH_SPLIT_EPSILON_PCT
    return {
        "rule": 2, "name": "Ash-split closure",
        "status": "pass" if ok else "fail",
        "message": (
            f"bed+cyclone+APH+ESP distribution = {total:.3f}% (must be exactly 100%)"
            + ("" if ok else " -- data-entry error, not auto-normalized.")
        ),
        "applies_to": "refuse.*_distribution_pct",
    }


def check_o2_rise_across_aph(o2_econ: float, o2_aph: float, o2_aph_is_real: bool) -> dict[str, Any]:
    rise = o2_aph - o2_econ
    if rise < 0:
        status, msg = "fail", f"O2 rise across air heater is {rise:+.2f}pp (negative) -- sensor/data error."
    elif rise > RULE_O2_RISE_FLAG_PP:
        status, msg = "warn", f"O2 rise across air heater is {rise:+.2f}pp (>2pp) -- possible excessive APH air in-leakage, flag for inspection."
    else:
        typical = RULE_O2_RISE_TYPICAL_MIN_PP <= rise <= RULE_O2_RISE_TYPICAL_MAX_PP
        status = "pass"
        msg = f"O2 rise across air heater is {rise:+.2f}pp ({'within' if typical else 'below/above but under the 2pp flag threshold of'} typical 0.3-1.5pp)."
    if not o2_aph_is_real:
        status = "not_checkable"
        msg += (" NOTE: O2 at the air-heater outlet is still the library's placeholder "
                "(no real sensor exists downstream of the air heater -- ask-list item #4), "
                "so this rise figure is not yet trustworthy.")
    return {
        "rule": 4, "name": "O2 rise across air heater (in-leakage)",
        "status": status, "message": msg,
        "applies_to": "gas.o2_economizer_outlet_dry_pct, gas.o2_air_heater_outlet_dry_pct",
    }


def check_monotonic_gas_temp(
    econ_inlet: float | None, econ_outlet: float | None, stack: float | None
) -> dict[str, Any]:
    chain = [("Economizer Inlet", econ_inlet), ("Economizer Outlet (APH Inlet)", econ_outlet), ("Stack", stack)]
    present = [(n, v) for n, v in chain if v is not None]
    base_note = (
        "Checked subset only -- Furnace, SH, APH Outlet, and ESP Outlet gas "
        "temperatures have no confirmed real tag (ask-list item #3): "
    )
    if len(present) < 2:
        return {
            "rule": 5, "name": "Monotonic flue-gas temperature",
            "status": "not_checkable",
            "message": base_note + "insufficient real gas-path readings this tick.",
            "applies_to": "gas.gas_temp_*, all FG TEMP tags",
        }
    violations = [
        f"{present[i][0]} ({present[i][1]:.1f}C) <= {present[i + 1][0]} ({present[i + 1][1]:.1f}C)"
        for i in range(len(present) - 1) if present[i][1] <= present[i + 1][1]
    ]
    ok = not violations
    chain_str = " > ".join(f"{n} {v:.1f}C" for n, v in present)
    return {
        "rule": 5, "name": "Monotonic flue-gas temperature",
        "status": "pass" if ok else "fail",
        "message": base_note + chain_str + (
            ". OK." if ok else ". Reversal(s) -- re-verify tag mapping/transmitter: " + "; ".join(violations)
        ),
        "applies_to": "gas.gas_temp_*, all FG TEMP tags",
    }


# O2 LHS/RHS: absolute tolerance instead of the document's relative 5%,
# per user's explicit direction (2026-08-13). The two O2 probes read a
# small-magnitude quantity (typically 3-5%), so a small absolute gap
# balloons into a large relative percentage -- confirmed via a full
# 73,427-row sweep: 56.94% of ticks exceeded the 5% relative tolerance,
# but the median ABSOLUTE gap was only 0.23pp. Same class of problem
# decision 10 already fixed for Drum Level/Furnace Draft with z-score/
# absolute-deviation zoning instead of %-deviation. Also matches how O2
# analyzer accuracy is conventionally specified in industry (absolute
# %O2, not %-of-reading).
#
# Value (0.85pp) is the observed p90 absolute gap from that same sweep --
# a data-derived CANDIDATE, not a number either source document states.
# status: configurable_pending_confirmation in
# hindalco_boiler9_pai_s02_v1.yaml scoring.* -- same treatment as the
# DGL/Fly-Ash setpoints (needs_verification), not silently final. The
# other 3 A/B pairs (Steam Flow, SH-3 Pressure, SH-3 Temp) stay on the
# document's relative 5% -- they operate at high-enough levels (100+ TPH,
# 90+ kg/cm2, 500+ C) that relative framing doesn't have O2's
# small-denominator problem.
RULE_O2_AB_ABSOLUTE_TOLERANCE_PP = 0.85
RULE_AB_ABSOLUTE_TOLERANCE_PAIRS = {"O2 LHS/RHS": RULE_O2_AB_ABSOLUTE_TOLERANCE_PP}


def check_ab_deviation(pairs: dict[str, tuple[float | None, float | None]]) -> list[dict[str, Any]]:
    out = []
    for name, (a, b) in pairs.items():
        if a is None or b is None:
            out.append({
                "rule": 6, "name": f"A/B deviation -- {name}",
                "status": "not_checkable", "message": "Missing A or B reading this tick.",
                "applies_to": "boiler_duty.*, gas.o2_*",
            })
            continue

        abs_tolerance = RULE_AB_ABSOLUTE_TOLERANCE_PAIRS.get(name)
        if abs_tolerance is not None:
            abs_gap = abs(a - b)
            ok = abs_gap <= abs_tolerance
            out.append({
                "rule": 6, "name": f"A/B deviation -- {name}",
                "status": "pass" if ok else "warn",
                "message": (
                    f"A={a:.2f}, B={b:.2f}, |A-B|={abs_gap:.2f}pp "
                    f"({'within' if ok else 'EXCEEDS'} {abs_tolerance:.2f}pp ABSOLUTE tolerance "
                    f"-- not the document's relative 5%, switched 2026-08-13 after a full-sweep "
                    f"finding (56.94% of ticks exceeded 5% relative, mostly a small-denominator "
                    f"artifact; this value is a data-derived candidate, not document-specified)"
                    + ("" if ok else "; do not blindly average, investigate the outlier instrument first")
                    + ")."
                ),
                "applies_to": "boiler_duty.*, gas.o2_*",
            })
            continue

        avg = (a + b) / 2.0
        dev_pct = abs(a - b) / avg * 100.0 if avg else 0.0
        ok = dev_pct <= RULE_AB_DEVIATION_MAX_PCT
        out.append({
            "rule": 6, "name": f"A/B deviation -- {name}",
            "status": "pass" if ok else "warn",
            "message": (
                f"A={a:.2f}, B={b:.2f}, |A-B|/avg={dev_pct:.2f}% "
                f"({'within' if ok else 'EXCEEDS'} {RULE_AB_DEVIATION_MAX_PCT:.0f}% tolerance"
                + ("" if ok else " -- do not blindly average, investigate the outlier instrument first")
                + ")."
            ),
            "applies_to": "boiler_duty.*, gas.o2_*",
        })
    return out


def check_feedwater_steam_balance(feedwater_flow: float, main_steam_flow: float) -> dict[str, Any]:
    if not main_steam_flow:
        return {
            "rule": 7, "name": "Steam/Feedwater mass balance",
            "status": "not_checkable", "message": "Main Steam Flow is zero/unavailable.",
            "applies_to": "boiler_duty.FEEDWATER_FLOW vs MAIN_STEAM_FLOW",
        }
    dev_pct = (feedwater_flow - main_steam_flow) / main_steam_flow * 100.0
    ok = abs(dev_pct) <= RULE_FEEDWATER_STEAM_BALANCE_TOLERANCE_PCT
    return {
        "rule": 7, "name": "Steam/Feedwater mass balance",
        "status": "pass" if ok else "warn",
        "message": (
            f"Feedwater {feedwater_flow:.1f} TPH vs Main Steam {main_steam_flow:.1f} TPH, "
            f"deviation {dev_pct:+.2f}% (tolerance used: +/-{RULE_FEEDWATER_STEAM_BALANCE_TOLERANCE_PCT:.0f}%, "
            f"the doc's own stated range is 3-5%, ambiguous which exact number -- outer/"
            f"lenient bound used here). No Blowdown/Spray Water Flow term included -- "
            f"neither has a real tag, same gap already documented for Cluster 1's own "
            f"Water-Steam Balance check."
            + ("" if ok else " Large mismatch -> check spray/attemperator (CV-116/CV-121) and blowdown status.")
        ),
        "applies_to": "boiler_duty.FEEDWATER_FLOW vs MAIN_STEAM_FLOW",
    }


def check_bed_ash_temperature(value: float, is_real: bool) -> dict[str, Any]:
    in_bed = RULE_BED_ASH_INBED_RANGE_C[0] <= value <= RULE_BED_ASH_INBED_RANGE_C[1]
    post_cooler = RULE_BED_ASH_POSTCOOLER_RANGE_C[0] <= value <= RULE_BED_ASH_POSTCOOLER_RANGE_C[1]
    if in_bed:
        status, msg = "pass", f"{value:.0f}C matches the in-bed range (850-950C)."
    elif post_cooler:
        status, msg = "warn", f"{value:.0f}C matches the POST-ASH-COOLER range (150-250C), not in-bed -- confirm this matches what the calculation model expects, else re-map."
    else:
        status, msg = "warn", f"{value:.0f}C matches NEITHER the in-bed (850-950C) nor post-cooler (150-250C) range."
    if not is_real:
        status = "not_checkable"
        msg += (" NOTE: still the library's reference-coal placeholder, not a real plant "
                "reading -- ash temperatures were not part of the 2026-08-13 document "
                "(ask-list item #15).")
    return {"rule": 8, "name": "Bed-ash temperature sanity", "status": status, "message": msg, "applies_to": "refuse.bed_ash_temperature_c"}


def check_ubc_order(refuse_kwargs: dict[str, Any]) -> dict[str, Any]:
    bed = refuse_kwargs["bed_ash_unburned_carbon_pct"]
    cyclone = refuse_kwargs["cyclone_ash_unburned_carbon_pct"]
    aph = refuse_kwargs["aph_ash_unburned_carbon_pct"]
    esp = refuse_kwargs["esp_ash_unburned_carbon_pct"]
    ok = bed >= esp >= cyclone >= aph
    return {
        "rule": 9, "name": "Unburned-carbon distribution order-of-magnitude",
        "status": "pass" if ok else "warn",
        "message": (
            f"Bed={bed}%, ESP={esp}%, Cyclone={cyclone}%, APH={aph}% -- expected order "
            f"Bed > ESP > Cyclone > APH (coarser particles carry more UBC) -- "
            f"{'follows' if ok else 'does NOT follow'} this pattern."
        ),
        "applies_to": "refuse.*_unburned_carbon_pct",
    }


def check_ambient_currency() -> dict[str, Any]:
    return {
        "rule": 10, "name": "Ambient data currency",
        "status": "not_checkable",
        "message": (
            "Cannot be verified programmatically -- there is no distinct 'boiler test "
            "window timestamp' field separate from the ambient document's own date "
            f"({PLANT_ENGINEERING_DOC_DATE.date().isoformat()}) to compare against. "
            "Flagged for manual confirmation with the plant/document owner that these "
            "were logged at the same timestamp as an actual test window (site "
            "met-station or handheld), not a daily average -- ask-list item #34."
        ),
        "applies_to": "ambient.*",
    }


def check_fixed_constants(h2o_factor: float, ubc_heating_value: float) -> dict[str, Any]:
    ok = h2o_factor == RULE_ASME_HYDROGEN_TO_WATER_FACTOR and ubc_heating_value == RULE_ASME_UBC_HEATING_VALUE_KJ_KG
    return {
        "rule": 11, "name": "Fixed-constant lock",
        "status": "pass" if ok else "warn",
        "message": (
            f"hydrogen_to_water_factor={h2o_factor} (ASME: {RULE_ASME_HYDROGEN_TO_WATER_FACTOR}), "
            f"unburned_carbon_heating_value_kj_kg={ubc_heating_value} "
            f"(ASME: {RULE_ASME_UBC_HEATING_VALUE_KJ_KG})"
            + ("" if ok else " -- differs from ASME PTC 4.1 standard constants; requires a documented reason/alternate code reference if intentional.")
        ),
        "applies_to": "assumptions.hydrogen_to_water_factor, assumptions.unburned_carbon_heating_value_kj_kg",
    }


def check_spent_sorbent(value: float) -> dict[str, Any]:
    if value == 0:
        return {
            "rule": 12, "name": "Spent sorbent verification",
            "status": "not_checkable",
            "message": (
                "spent_sorbent_lbm_per_100_lbm_fuel=0 (library default) is only valid if "
                "this CFBC unit has NO active limestone/sorbent injection -- not yet "
                "confirmed either way. If dosing IS active, this input MUST be non-zero "
                "-- verify with DM/limestone feeder logs before accepting 0. Ask-list item #35."
            ),
            "applies_to": "assumptions.spent_sorbent_lbm_per_100_lbm_fuel",
        }
    return {
        "rule": 12, "name": "Spent sorbent verification", "status": "pass",
        "message": f"spent_sorbent_lbm_per_100_lbm_fuel={value} (non-zero -- sorbent injection assumed confirmed active).",
        "applies_to": "assumptions.spent_sorbent_lbm_per_100_lbm_fuel",
    }


def check_steam_design_limits(pressure: float, temperature: float) -> dict[str, Any]:
    ok = pressure <= RULE_MAIN_STEAM_PRESSURE_MAX_KG_CM2 and temperature <= RULE_MAIN_STEAM_TEMPERATURE_MAX_C
    return {
        "rule": 13, "name": "Steam parameter design-limit check",
        "status": "pass" if ok else "fail",
        "message": (
            f"Pressure={pressure:.1f} kg/cm2(a) (limit {RULE_MAIN_STEAM_PRESSURE_MAX_KG_CM2:.0f}), "
            f"Temperature={temperature:.1f}C (limit {RULE_MAIN_STEAM_TEMPERATURE_MAX_C:.0f})"
            + ("" if ok else " -- OUTSIDE design envelope, possible transmitter fault or abnormal operating condition, hold the test.")
        ),
        "applies_to": "boiler_duty.MAIN_STEAM_PRESSURE, MAIN_STEAM_TEMPERATURE",
    }


def check_load_stability(history: list[float]) -> dict[str, Any]:
    window = history[-RULE_LOAD_STABILITY_WINDOW_ROWS:]
    if len(window) < RULE_LOAD_STABILITY_WINDOW_ROWS:
        return {
            "rule": 14, "name": "Load stability window",
            "status": "not_checkable",
            "message": f"Only {len(window)} of {RULE_LOAD_STABILITY_WINDOW_ROWS} rows of history available yet (replay just started/reset).",
            "applies_to": "boiler_duty.MAIN_STEAM_FLOW",
        }
    mean = sum(window) / len(window)
    if mean == 0:
        return {
            "rule": 14, "name": "Load stability window",
            "status": "not_checkable", "message": "Main Steam Flow mean is zero over the window.",
            "applies_to": "boiler_duty.MAIN_STEAM_FLOW",
        }
    max_dev_pct = max(abs(v - mean) / mean * 100.0 for v in window)
    ok = max_dev_pct <= RULE_LOAD_STABILITY_TOLERANCE_PCT
    return {
        "rule": 14, "name": "Load stability window",
        "status": "pass" if ok else "warn",
        "message": (
            f"Main Steam Flow over last {RULE_LOAD_STABILITY_WINDOW_ROWS} rows "
            f"(~60 min at this dataset's 5-min interval): mean={mean:.1f} TPH, "
            f"max deviation={max_dev_pct:.2f}% "
            f"({'within' if ok else 'EXCEEDS'} +/-{RULE_LOAD_STABILITY_TOLERANCE_PCT:.0f}% tolerance"
            + ("" if ok else " -- reject, likely captured during ramp-up/ramp-down or a load swing")
            + ")."
        ),
        "applies_to": "boiler_duty.MAIN_STEAM_FLOW",
    }


def run_validation_checks(
    refuse_kwargs: dict[str, Any],
    assumptions_kwargs: dict[str, Any],
    boiler_duty_kwargs: dict[str, Any],
    o2_econ: float,
    ab_instruments: dict[str, float | None],
    gas_path_temps: dict[str, float | None],
    steam_flow_history: list[float],
) -> list[dict[str, Any]]:
    """Rules 4-14 (advisory). Rules 1, 2 (blocking gates) and 3 (cross-
    referenced from the GCV Check the library itself computes) are NOT
    included here -- run_efficiency() computes those three separately
    (rules 1/2 must run BEFORE the library is even called, since they can
    block the run entirely; rule 3 needs the library's own output, which
    doesn't exist yet when this function would need to run) and merges all
    14 into one sorted list. `refuse_kwargs` is used by rules 8/9 (bed-ash
    temperature, UBC order)."""
    checks = [
        check_o2_rise_across_aph(
            o2_econ, _REFERENCE_COAL["gas"]["o2_air_heater_outlet_dry_pct"], o2_aph_is_real=False,
        ),
        check_monotonic_gas_temp(
            gas_path_temps.get("econ_inlet_c"), gas_path_temps.get("econ_outlet_c"), gas_path_temps.get("stack_c"),
        ),
    ]
    checks.extend(check_ab_deviation({
        "Steam Flow A/B": (ab_instruments.get("steam_flow_a"), ab_instruments.get("steam_flow_b")),
        "SH-3 Pressure A/B": (ab_instruments.get("sh3_pressure_a"), ab_instruments.get("sh3_pressure_b")),
        "SH-3 Temp A/B": (ab_instruments.get("sh3_temp_a"), ab_instruments.get("sh3_temp_b")),
        "O2 LHS/RHS": (ab_instruments.get("o2_lhs"), ab_instruments.get("o2_rhs")),
    }))
    checks.append(check_feedwater_steam_balance(boiler_duty_kwargs["FEEDWATER_FLOW"], boiler_duty_kwargs["MAIN_STEAM_FLOW"]))
    checks.append(check_bed_ash_temperature(refuse_kwargs["bed_ash_temperature_c"], is_real=False))
    checks.append(check_ubc_order(refuse_kwargs))
    checks.append(check_ambient_currency())
    checks.append(check_fixed_constants(
        assumptions_kwargs["hydrogen_to_water_factor"], assumptions_kwargs["unburned_carbon_heating_value_kj_kg"],
    ))
    checks.append(check_spent_sorbent(assumptions_kwargs["spent_sorbent_lbm_per_100_lbm_fuel"]))
    checks.append(check_steam_design_limits(boiler_duty_kwargs["MAIN_STEAM_PRESSURE"], boiler_duty_kwargs["MAIN_STEAM_TEMPERATURE"]))
    checks.append(check_load_stability(steam_flow_history))
    checks.sort(key=lambda c: c["rule"])
    return checks


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
    "real", "stale", "simulated", "static_config", plus "documented"
    (added 2026-08-13) -- a real value from a plant engineering document
    (fuel.*, refuse.*_distribution_pct/_unburned_carbon_pct, ambient.*,
    gcv_check.*), deliberately distinct from "static_config" (a generic
    Awes/library engineering default with no plant-specific override,
    e.g. assumptions.*, enthalpy.reference_water_temperature_c,
    gas.flue_gas_specific_heat_cpg_btu_lbm_f) -- both render as chips, but
    "documented" should read as "a confirmed plant number" and
    "static_config" as "a generic placeholder pending confirmation", not
    the same thing. assumption_notes carries the longer prose explanations
    (e.g. the O2 tap-location assumption below) that don't fit a one-word
    chip, for the frontend's Data Source / Assumptions panel."""

    data_source: dict[str, str] = {}
    assumption_notes: list[str] = []

    # RESOLVED 2026-08-13: real Ultimate + Proximate Analysis from a plant
    # engineering document (ask-list item #14), superseding the reference-
    # coal placeholder. hhv_kj_kg uses THIS document's own value (14870),
    # not GCV_KJ_PER_KG (Module 1's separate COAL_GCV constant, ~1.6%
    # higher, different source) -- see GCV_KCAL_PER_KG's comment above for
    # why those two are deliberately kept independent (Gate 1).
    fuel_kwargs = {
        **FUEL_ULTIMATE_PROXIMATE,
        "hhv_kj_kg": FUEL_HHV_KJ_KG,
        "name": "Hindalco Boiler-9 coal (plant engineering document, 2026-08-13)",
    }
    for k in FUEL_ULTIMATE_PROXIMATE:
        data_source[f"fuel.{k}"] = "documented"
    # Gate: GCV staleness (spec, >8h -> "GCV Data Stale"). This gate models
    # a per-shift LIVE lab entry, per the spec's own framing -- GCV_LAST_UPDATED
    # is still process-start time (no real per-shift entry mechanism exists
    # yet, see GCV_LAST_UPDATED's own comment; ask-list item on the
    # per-shift workflow is still open) -- won't trigger within one server
    # run, but the check is real and independently testable. Deliberately
    # NOT reset to PLANT_ENGINEERING_DOC_DATE: this document is a periodic
    # test-report figure, not a per-shift one, so treating its age against
    # an 8-hour per-shift threshold would misrepresent it as needing hourly
    # refresh -- a different cadence question, tracked separately (see
    # PLANT_ENGINEERING_DOC_DATE's own comment above).
    gcv_stale = gcv_is_stale()
    data_source["fuel.hhv_kj_kg"] = "stale" if gcv_stale else "documented"
    assumption_notes.append(
        f"fuel.*: real Ultimate + Proximate Analysis from a plant engineering "
        f"document, last updated {PLANT_ENGINEERING_DOC_DATE.date().isoformat()} "
        f"({plant_doc_age_days():.0f} days ago) -- supersedes the library's "
        f"bundled reference-coal placeholder. Same lab report unblocks Module 2 "
        f"(PAI-S03)'s afr_design too."
    )

    # RESOLVED (partial) 2026-08-13: real ash distribution %/unburned-carbon
    # % from the same document (ask-list item #15) -- ash TEMPERATURES were
    # not part of it and still come from the reference-coal placeholder
    # (bed/cyclone/APH/ESP temperatures), a deliberate real+placeholder mix
    # per the config's own note (same reasoning already applied to
    # cyclone_ash_temperature_c's candidate-tag deferral).
    refuse_kwargs = {
        **REFUSE_ASH_SPLIT,
        "bed_ash_temperature_c": _REFERENCE_COAL["refuse"]["bed_ash_temperature_c"],
        "cyclone_ash_temperature_c": _REFERENCE_COAL["refuse"]["cyclone_ash_temperature_c"],
        "aph_ash_temperature_c": _REFERENCE_COAL["refuse"]["aph_ash_temperature_c"],
        "esp_ash_temperature_c": _REFERENCE_COAL["refuse"]["esp_ash_temperature_c"],
    }
    for k in REFUSE_ASH_SPLIT:
        data_source[f"refuse.{k}"] = "documented"
    for k in ("bed_ash_temperature_c", "cyclone_ash_temperature_c", "aph_ash_temperature_c", "esp_ash_temperature_c"):
        data_source[f"refuse.{k}"] = "simulated"
    assumption_notes.append(
        f"refuse.*: ash distribution % and unburned-carbon % per stream are "
        f"real (same plant engineering document as fuel.*, last updated "
        f"{PLANT_ENGINEERING_DOC_DATE.date().isoformat()}). Ash TEMPERATURES "
        f"per stream were NOT part of that document and still use the "
        f"reference coal's placeholder values -- a deliberate, documented "
        f"real+placeholder mix, not a silent default."
    )

    # RESOLVED 2026-08-13 (ask-list item #16): explicit static design-basis
    # ambient values from the same document. "documented", not "real" --
    # not a live tag, not in the historian export.
    ambient_kwargs = dict(AMBIENT_CONDITIONS)
    for k in ambient_kwargs:
        data_source[f"ambient.{k}"] = "documented"
    assumption_notes.append(
        f"ambient.*: static design-basis values from the same plant "
        f"engineering document as fuel.*/refuse.* above, last updated "
        f"{PLANT_ENGINEERING_DOC_DATE.date().isoformat()} -- still not a live "
        f"tag (not in the historian export), so tagged documented rather "
        f"than real."
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

    # Cross-confirmed 2026-08-13 by the same plant engineering document as
    # fuel.*/refuse.*/ambient.* above (see config's gcv_check.* note) --
    # "documented", not the generic "static_config" a library-default value
    # would get.
    gcv_check_kwargs = {"lower": GCV_CHECK_LOWER, "upper": GCV_CHECK_UPPER, "apply_correction": False}
    for k in gcv_check_kwargs:
        data_source[f"gcv_check.{k}"] = "documented"

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
    ab_instruments: dict[str, float | None] | None = None,
    gas_path_temps: dict[str, float | None] | None = None,
    steam_flow_history: list[float] | None = None,
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

    `ab_instruments`/`gas_path_temps`/`steam_flow_history` feed the 2026-08-13
    Logical Filtering & Validation Rules (advisory checks 4-6, 14; see
    run_validation_checks()'s docstring) -- optional so existing callers/
    tests that don't pass them still work, just with those specific checks
    returning "not_checkable" instead of a real result.
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

    # ---- Rules 1 & 2 (Logical Filtering & Validation Rules, 2026-08-13):
    # the spec's own stated action for both is to NOT proceed with the
    # efficiency run at all -- real blocking gates, not advisory checks.
    # Reuses the exact same check functions run_validation_checks() calls
    # for the full 14-rule list later, so there's one implementation each,
    # not duplicated logic between "blocking" and "advisory" paths. ----
    mass_closure_check = check_mass_closure(kwargs["fuel"])
    ash_split_check = check_ash_split_closure(kwargs["refuse"])
    blocking_failures = [c for c in (mass_closure_check, ash_split_check) if c["status"] == "fail"]
    if blocking_failures:
        return {
            "status": "invalid_inputs",
            "error": "Validation rule failure -- " + "; ".join(f"Rule {c['rule']} ({c['name']}): {c['message']}" for c in blocking_failures),
            "data_source": {},
            "assumption_notes": [],
            "warnings": [],
            "validation_checks": [mass_closure_check, ash_split_check],
        }

    # Built once so run_validation_checks() (rules 11, 12) can read the
    # ACTUAL field values (kwargs["assumptions"] is deliberately {} --
    # "EfficiencyAssumptions() library defaults used as-is" -- so the
    # dataclass instance, not the raw empty kwargs dict, is the only place
    # those values exist).
    assumptions_obj = EfficiencyAssumptions(**kwargs["assumptions"])

    try:
        result = run_energy_balance(
            FuelAnalysis(**kwargs["fuel"]),
            RefuseAnalysis(**kwargs["refuse"]),
            AmbientConditions(**kwargs["ambient"]),
            GasMeasurements(**kwargs["gas"]),
            EnthalpyInputs(**kwargs["enthalpy"]),
            assumptions_obj,
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
            "which is circular -- see this module's docstring) x GCV_KCAL_PER_KG "
            "(3610 kcal/kg, Module 1's COAL_GCV). Measured (2000-tick offline "
            "sweep, 2026-08-13): even with real fuel.* now wired in, this still "
            "disagrees with eta_indirect on 99.8% of ticks -- not because fuel "
            "composition is fake anymore (it isn't), but because (a) fuel.*/"
            "refuse.*/ambient.* are all STATIC values that don't vary tick-to-"
            "tick, so eta_indirect itself barely moves (87.52-87.66% in the "
            "sweep) while eta_direct is highly volatile (37-92%), driven by "
            "real Fuel Flow tag noise against a GCV constant that itself, and "
            "(b) GCV_KCAL_PER_KG (3610 kcal/kg / 15114.3 kJ/kg) differs ~1.64% "
            "from fuel.hhv_kj_kg's own real value (14870 kJ/kg / 3551.6 "
            "kcal/kg) -- two different documents, kept deliberately independent "
            "(see GCV_KCAL_PER_KG's own comment) rather than reconciled, which "
            "adds a small systematic offset on top of Fuel Flow's own noise."
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

    # ---- Logical Filtering & Validation Rules, 2026-08-13 -- rules 4-14
    # (advisory) plus rules 1/2 (already evaluated above as blocking gates,
    # included again here so this is always the complete 14-rule list) and
    # rule 3 (cross-referenced from the GCV Check the library just computed
    # above, not recomputed). ----
    gcv_vals = result["gcv_check"]["values"]
    rule_3 = {
        "rule": 3, "name": "GCV cross-check band",
        "status": "pass" if gcv_vals["correction_required"] == 0 else "warn",
        "message": (
            f"g_factor={gcv_vals['g_factor']:.4f} (band [{GCV_CHECK_LOWER:.2f}, {GCV_CHECK_UPPER:.2f}]) -- "
            "this IS the existing GCV Check mechanism (Phase A Gate 2's sibling), not a "
            "separate computation."
            + (" Outside band, apply_correction=False -> flagged for lab HHV re-check (not auto-corrected)." if gcv_vals["correction_required"] else "")
        ),
        "applies_to": "fuel.hhv_kj_kg vs gcv_check",
    }
    result["validation_checks"] = sorted(
        [mass_closure_check, ash_split_check, rule_3] + run_validation_checks(
            refuse_kwargs=kwargs["refuse"],
            assumptions_kwargs={
                "hydrogen_to_water_factor": assumptions_obj.hydrogen_to_water_factor,
                "unburned_carbon_heating_value_kj_kg": assumptions_obj.unburned_carbon_heating_value_kj_kg,
                "spent_sorbent_lbm_per_100_lbm_fuel": assumptions_obj.spent_sorbent_lbm_per_100_lbm_fuel,
            },
            boiler_duty_kwargs=kwargs["boiler_duty"],
            o2_econ=o2_value,
            ab_instruments=ab_instruments or {},
            gas_path_temps=gas_path_temps or {},
            steam_flow_history=steam_flow_history or [],
        ),
        key=lambda c: c["rule"],
    )

    result["status"] = "ok"
    result["data_source"] = data_source
    result["assumption_notes"] = assumption_notes
    return result
