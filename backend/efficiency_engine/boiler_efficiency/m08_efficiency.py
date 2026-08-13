"""M08 - ASME PTC 4 energy-balance heat losses and credits."""

from .models import FuelAnalysis, EfficiencyAssumptions, ModuleResult


def residue_enthalpy_btu_lbm(temp_c: float) -> float:
    temp_f = temp_c * 9.0 / 5.0 + 32.0

    return (
        0.16 * temp_f
        + 1.09e-4 * temp_f**2
        - 2.843e-8 * temp_f**3
        - 12.95
    )


def calculate_efficiency(
    f: FuelAnalysis,
    refuse_values,
    gas_values,
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
    a: EfficiencyAssumptions = EfficiencyAssumptions()
) -> ModuleResult:

    hhv = f.hhv_kj_kg

    dry_gas = gas_values["dry_flue_gas_economizer_kg_kg_fuel"]
    water_h2 = gas_values["water_from_hydrogen_kg_kg_fuel"]
    water_f = f.moisture_pct / 100.0

    humidity_ratio = (
        gas_values["air_moisture_economizer_kg_kg_fuel"]
        / gas_values["dry_air_economizer_kg_kg_fuel"]
    )

    da9 = gas_values["dry_air_economizer_kg_kg_fuel"]
    da8 = gas_values["dry_air_ah_outlet_kg_kg_fuel"]

    ubc = refuse_values["unburned_carbon_kg_kg_fuel"]

    hhv_btu_lbm = hhv / 2.326

    unburned_carbon_lbm_per_100_lbm_fuel = (
        refuse_values["unburned_carbon_kg_kg_fuel"] * 100.0
    )

    total_residue_lbm_per_100_lbm_fuel = (
        f.ash_pct
        + a.spent_sorbent_lbm_per_100_lbm_fuel
        + unburned_carbon_lbm_per_100_lbm_fuel
    )

    total_residue_lbm_per_10kbtu = (
        100.0
        * total_residue_lbm_per_100_lbm_fuel
        / hhv_btu_lbm
    )

    bed_residue_h = residue_enthalpy_btu_lbm(
        refuse_values["bed_ash_temperature_c"]
    )

    cyclone_residue_h = residue_enthalpy_btu_lbm(
        refuse_values["cyclone_ash_temperature_c"]
    )

    aph_residue_h = residue_enthalpy_btu_lbm(
        refuse_values["aph_ash_temperature_c"]
    )

    esp_residue_h = residue_enthalpy_btu_lbm(
        refuse_values["esp_ash_temperature_c"]
    )

    sensible_heat_loss_pct = (
        refuse_values["bed_ash_distribution_pct"]
        * total_residue_lbm_per_10kbtu
        * bed_residue_h
        / 10000.0

        + refuse_values["cyclone_ash_distribution_pct"]
        * total_residue_lbm_per_10kbtu
        * cyclone_residue_h
        / 10000.0

        + refuse_values["aph_ash_distribution_pct"]
        * total_residue_lbm_per_10kbtu
        * aph_residue_h
        / 10000.0

        + refuse_values["esp_ash_distribution_pct"]
        * total_residue_lbm_per_10kbtu
        * esp_residue_h
        / 10000.0
    )

    losses = {
        "dry_flue_gas_loss_pct": dry_gas
        * (dry_gas_exit_kj_kg - dry_gas_reference_kj_kg)
        / hhv
        * 100.0,

        "hydrogen_moisture_loss_pct": water_h2
        * (water_vapor_stack_kj_kg - water_reference_kj_kg)
        / hhv
        * 100.0,

        "fuel_moisture_loss_pct": water_f
        * (water_vapor_stack_kj_kg - water_reference_kj_kg)
        / hhv
        * 100.0,

        "air_moisture_loss_pct": humidity_ratio
        * da9
        * water_vapor_exit_kj_kg
        / hhv
        * 100.0,

        "unburned_carbon_loss_pct": ubc
        * a.unburned_carbon_heating_value_kj_kg
        / hhv
        * 100.0,

        "sensible_heat_loss_pct": sensible_heat_loss_pct,

        "surface_radiation_loss_pct": a.surface_radiation_loss_pct,
        "other_loss_pct": a.other_loss_pct,
    }

    credits = {
        "entering_dry_air_credit_pct": da8
        * dry_air_entering_kj_kg
        / hhv
        * 100.0,

        "entering_air_moisture_credit_pct": humidity_ratio
        * da8
        * water_vapor_entering_kj_kg
        / hhv
        * 100.0,

        "fuel_sensible_heat_credit_pct": fuel_entering_kj_kg
        / hhv
        * 100.0,

        "auxiliary_power_credit_pct": a.auxiliary_power_credit_pct,
    }

    total_loss = sum(losses.values())
    total_credit = sum(credits.values())

    efficiency = 100.0 - total_loss + total_credit

    return ModuleResult(
        {
            **losses,
            **credits,
            "total_heat_loss_pct": total_loss,
            "total_heat_credit_pct": total_credit,
            "boiler_efficiency_hhv_pct": efficiency,
        }
    )
