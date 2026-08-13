"""Coordinates the module-wise calculation."""

from .validation import validate_fuel
from .m04_combustion import calculate_refuse
from .m05_psychrometrics import humidity_ratio
from .m06_air_flue_gas import calculate_air_and_flue_gas
from .m08_efficiency import calculate_efficiency
from .m09_corrections import appendix_d4_corrections
from .m01_boiler_duty import calculate_boiler_duty
from CoolProp.CoolProp import PropsSI
from .m02_fuel import normalize_fuel
from .m03_gcv import validate_and_correct
from .m07_firing import calculate_firing


def run_energy_balance(
    fuel,
    refuse,
    ambient,
    gas,
    enthalpy,
    assumptions,
    boiler_duty,
    gcv_check,
):
    fuel = normalize_fuel(fuel)

    fuel, gcv = validate_and_correct(
        fuel,
        gcv_check.lower,
        gcv_check.upper,
        gcv_check.apply_correction,
    )

    warnings = validate_fuel(fuel)

    psy = humidity_ratio(ambient)
    moisture_in_air = psy.values["humidity_ratio_kg_kg_dry_air"]

    gas_temp_ah_outlet_k = gas.gas_temp_air_heater_outlet_c + 273.0
    air_temp_ah_inlet_k = gas.air_temp_air_heater_inlet_c + 273.0

    ref = calculate_refuse(fuel, refuse)

    fg = calculate_air_and_flue_gas(
        fuel,
        ref.values["carbon_burned_pct"],
        gas.o2_economizer_outlet_dry_pct,
        gas.o2_air_heater_outlet_dry_pct,
        psy.values["humidity_ratio_kg_kg_dry_air"],
        assumptions,
    )

    ms_enthalpy_kj_kg = PropsSI(
        "H",
        "P",
        boiler_duty.MAIN_STEAM_PRESSURE * 98066.5,
        "T",
        boiler_duty.MAIN_STEAM_TEMPERATURE + 273.15,
        "Water",
    ) / 1000.0

    # water_reference_kj_kg = PropsSI(
        # "H",
        # "P",
        # 101325,
        # "T",
        # enthalpy.reference_water_temperature_c + 273.15,
        # "Water",
    # ) / 1000.0
    
    water_reference_kj_kg=((enthalpy.reference_water_temperature_c*1.8+32)-32)*2.326

    water_vapor_stack_kj_kg = PropsSI(
        "H",
        "P",
        101325,
        "T",
        gas.gas_temp_air_heater_outlet_c + 273.15,
        "Water",
    ) / 1000.0

    aa34 = (
        -0.1310658e3
        + 0.4581304 * gas_temp_ah_outlet_k
        - 0.1075033e-3 * gas_temp_ah_outlet_k**2
        + 0.1778848e-6 * gas_temp_ah_outlet_k**3
        - 0.9248664e-10 * gas_temp_ah_outlet_k**4
        + 0.16820314e-13 * gas_temp_ah_outlet_k**5
    )

    ab34 = (
        -0.2394034e3
        + 0.8274589 * gas_temp_ah_outlet_k
        - 0.1797539e-3 * gas_temp_ah_outlet_k**2
        + 0.393461e-6 * gas_temp_ah_outlet_k**3
        - 0.2415873e-9 * gas_temp_ah_outlet_k**4
        + 0.6069264e-13 * gas_temp_ah_outlet_k**5
    )

    enthalpy_air_leaving = (
        (1.0 - moisture_in_air) * aa34
        + moisture_in_air * ab34
    )

    aa35 = (
        -0.1310658e3
        + 0.4581304 * air_temp_ah_inlet_k
        - 0.1075033e-3 * air_temp_ah_inlet_k**2
        + 0.1778848e-6 * air_temp_ah_inlet_k**3
        - 0.9248664e-10 * air_temp_ah_inlet_k**4
        + 0.16820314e-13 * air_temp_ah_inlet_k**5
    )

    ab35 = (
        -0.2394034e3
        + 0.8274589 * air_temp_ah_inlet_k
        - 0.1797539e-3 * air_temp_ah_inlet_k**2
        + 0.393461e-6 * air_temp_ah_inlet_k**3
        - 0.2415873e-9 * air_temp_ah_inlet_k**4
        + 0.6069264e-13 * air_temp_ah_inlet_k**5
    )

    enthalpy_air_entering = (
        (1.0 - moisture_in_air) * aa35
        + moisture_in_air * ab35
    )

    gas_temp_ah_outlet_f = (
        gas.gas_temp_air_heater_outlet_c * 9.0 / 5.0
        + 32.0
    )

    air_ingress_fraction = fg.values["air_heater_leakage_pct"] / 100.0

    corrected_gas_temp_ah_outlet_f = (
        gas_temp_ah_outlet_f
        + (
            air_ingress_fraction
            * (enthalpy_air_leaving - enthalpy_air_entering)
            / gas.flue_gas_specific_heat_cpg_btu_lbm_f
        )
    )
    enthalpy_steam_fluegas_exit_kj_kg = (
        0.4329 * corrected_gas_temp_ah_outlet_f
        + 3.958e-5 * corrected_gas_temp_ah_outlet_f**2
        + 1062.2
    ) * 2.326
        
    corrected_gas_temp_ah_outlet_c = (
        corrected_gas_temp_ah_outlet_f - 32.0
    ) / 1.8

    t_gas = corrected_gas_temp_ah_outlet_c + 273.0

    water_vapor_exit_kj_kg = 2.236 * (
        -0.2394034e3
        + 0.8274589 * t_gas
        - 0.1797539e-3 * t_gas**2
        + 0.393461e-6 * t_gas**3
        - 0.2415873e-9 * t_gas**4
        + 0.6069264e-13 * t_gas**5
    )

    t_air = gas.air_temp_air_heater_inlet_c + 273.0

    dry_gas_exit_kj_kg = 2.236 * (
        -0.1231899e3
        + 0.4065568 * t_gas
        + 0.579505e-5 * t_gas**2
        + 0.6331121e-7 * t_gas**3
        - 0.2924434e-10 * t_gas**4
        + 0.2491009e-14 * t_gas**5
    )

    dry_air_entering_kj_kg = 2.236 * (
        -0.1310658e3
        + 0.4581304 * t_air
        - 0.1075033e-3 * t_air**2
        + 0.1778848e-6 * t_air**3
        - 0.9248664e-10 * t_air**4
        + 0.16820314e-13 * t_air**5
    )

    water_vapor_entering_kj_kg = 2.236 * (
        -0.2394034e3
        + 0.8274589 * t_air
        - 0.1797539e-3 * t_air**2
        + 0.393461e-6 * t_air**3
        - 0.2415873e-9 * t_air**4
        + 0.6069264e-13 * t_air**5
    )

    temp_f = ambient.fuel_temp_c * 9.0 / 5.0 + 32.0

    i10 = 0.152 * temp_f + 1.95e-4 * temp_f**2 - 12.86
    j10 = 0.38 * temp_f + 2.25e-4 * temp_f**2 - 30.594
    k10 = 0.17 * temp_f + 0.8e-4 * temp_f**2 - 13.564
    l10 = temp_f - 77.0

    fuel_entering_kj_kg = 2.236 * (
        fuel.fixed_carbon_pct / 100.0 * i10
        + fuel.volatile_matter_pct / 100.0 * j10
        + fuel.ash_pct / 100.0 * k10
        + fuel.moisture_pct / 100.0 * l10
    )

    t_air_ref = gas.air_temp_air_heater_inlet_c + 273.0

    dry_gas_reference_kj_kg = 2.326 * (
        -0.1310658e3
        + 0.4581304 * t_air_ref
        - 0.1075033e-3 * t_air_ref**2
        + 0.1778848e-6 * t_air_ref**3
        - 0.9248664e-10 * t_air_ref**4
        + 0.16820314e-13 * t_air_ref**5
    )

    eff = calculate_efficiency(
        fuel,
        ref.values,
        fg.values,
        ms_enthalpy_kj_kg,
        enthalpy_steam_fluegas_exit_kj_kg,
        water_reference_kj_kg,
        water_vapor_stack_kj_kg,
        dry_gas_exit_kj_kg,
        dry_gas_reference_kj_kg,
        water_vapor_exit_kj_kg,
        dry_air_entering_kj_kg,
        water_vapor_entering_kj_kg,
        fuel_entering_kj_kg,
        assumptions,
    )

    fan_temp = (
        gas.air_temp_fan_inlet_c
        if gas.air_temp_fan_inlet_c is not None
        else ambient.dry_bulb_c
    )

    corr = appendix_d4_corrections(
        eff.values["boiler_efficiency_hhv_pct"],
        fan_temp,
        psy.values["humidity_ratio_kg_kg_dry_air"],
        fuel,
    )

    fw_enthalpy_kj_kg = PropsSI(
        "H",
        "P",
        boiler_duty.FW_PR_TO_FCS * 98066.5,
        "T",
        boiler_duty.FEEDWATER_TEMP_TO_FCS + 273.15,
        "Water",
    ) / 1000.0

    ms_flow_kg_s = boiler_duty.MAIN_STEAM_FLOW * 1000.0 / 3600.0
    fw_flow_kg_s = boiler_duty.FEEDWATER_FLOW * 1000.0 / 3600.0

    boiler = calculate_boiler_duty(
        heat_leaving_streams={
            "main_steam": (
                ms_flow_kg_s,
                ms_enthalpy_kj_kg,
            )
        },
        heat_entering_streams={
            "feedwater": (
                fw_flow_kg_s,
                fw_enthalpy_kj_kg,
            )
        },
    )

    firing = calculate_firing(
        boiler.values["boiler_duty_mw"],
        fuel.hhv_kj_kg,
        eff.values["boiler_efficiency_hhv_pct"],
        fg.values["theoretical_air_kg_kg_fuel"],
    )

    enthalpy_values = {
        "steam_exit_kj_kg": enthalpy_steam_fluegas_exit_kj_kg,
        "water_reference_kj_kg": water_reference_kj_kg,
        "water_vapor_stack_kj_kg": water_vapor_stack_kj_kg,
        "dry_gas_exit_kj_kg": dry_gas_exit_kj_kg,
        "dry_gas_reference_kj_kg": dry_gas_reference_kj_kg,
        "dry_air_entering_kj_kg": dry_air_entering_kj_kg,
        "water_vapor_exit_kj_kg": water_vapor_exit_kj_kg,
        "water_vapor_entering_kj_kg": water_vapor_entering_kj_kg,
        "fuel_entering_kj_kg": fuel_entering_kj_kg,
    }

    gas_calculated_values = {
        "o2_air_heater_inlet_dry_pct": gas.o2_economizer_outlet_dry_pct,
        "o2_air_heater_outlet_dry_pct": gas.o2_air_heater_outlet_dry_pct,
        "air_heater_leakage_pct": fg.values["air_heater_leakage_pct"],
        "corrected_gas_temp_ah_outlet_c": corrected_gas_temp_ah_outlet_c,
        "enthalpy_air_leaving_btu_lbm": enthalpy_air_leaving,
        "enthalpy_air_entering_btu_lbm": enthalpy_air_entering,
        "enthalpy_air_difference_btu_lbm": (
            enthalpy_air_leaving - enthalpy_air_entering
        ),
    }

    return {
        "psychrometrics": psy.to_dict(),
        "refuse": ref.to_dict(),
        "air_flue_gas": fg.to_dict(),
        "enthalpy": enthalpy_values,
        "efficiency": eff.to_dict(),
        "corrections": corr.to_dict(),
        "boiler_duty": boiler.to_dict(),
        "fuel_firing": firing.to_dict(),
        "gcv_check": gcv.to_dict(),
        "gas_calculated": gas_calculated_values,
        "warnings": warnings,
    }