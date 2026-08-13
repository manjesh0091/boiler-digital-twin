"""M06 - Air and wet/dry flue-gas mass rates around the air heater."""
from .models import FuelAnalysis, ModuleResult, EfficiencyAssumptions
from .m04_combustion import theoretical_air_kg_kg, excess_air_from_o2, dry_gas_composition

def calculate_air_and_flue_gas(f, carbon_burned_pct, o2_econ, o2_ah, humidity_ratio, assumptions=EfficiencyAssumptions()):
    th=theoretical_air_kg_kg(carbon_burned_pct,f)
    ea14,_,_=excess_air_from_o2(o2_econ,carbon_burned_pct,f)
    ea15,_,_=excess_air_from_o2(o2_ah,carbon_burned_pct,f)
    da14=th*(1+ea14/100); da15=th*(1+ea15/100)
    wa14=humidity_ratio*da14; wa15=humidity_ratio*da15
    gas_from_fuel=(100-f.ash_pct)/100.0
    water_fuel=f.moisture_pct/100.0
    water_h2=assumptions.hydrogen_to_water_factor*f.hydrogen_pct/100.0
    water_fg14=water_fuel+water_h2+wa14+assumptions.additional_moisture_kg_kg_fuel
    water_fg15=water_fuel+water_h2+wa15+assumptions.additional_moisture_kg_kg_fuel
    wet14=da14+wa14+gas_from_fuel+assumptions.additional_moisture_kg_kg_fuel
    wet15=da15+wa15+gas_from_fuel+assumptions.additional_moisture_kg_kg_fuel
    dry14=wet14-water_fg14; dry15=wet15-water_fg15
    leakage=(wet15-wet14)/wet14*100
    vals={"theoretical_air_kg_kg_fuel":th,"excess_air_economizer_pct":ea14,
          "excess_air_air_heater_outlet_pct":ea15,"dry_air_economizer_kg_kg_fuel":da14,
          "dry_air_ah_outlet_kg_kg_fuel":da15,"air_moisture_economizer_kg_kg_fuel":wa14,
          "air_moisture_ah_outlet_kg_kg_fuel":wa15,"water_from_fuel_kg_kg_fuel":water_fuel,
          "water_from_hydrogen_kg_kg_fuel":water_h2,"wet_flue_gas_economizer_kg_kg_fuel":wet14,
          "wet_flue_gas_ah_outlet_kg_kg_fuel":wet15,"dry_flue_gas_economizer_kg_kg_fuel":dry14,
          "dry_flue_gas_ah_outlet_kg_kg_fuel":dry15,"air_heater_leakage_pct":leakage,
          "flue_gas_moisture_economizer_pct":100*water_fg14/wet14,
          "flue_gas_moisture_ah_outlet_pct":100*water_fg15/wet15}
    vals.update({f"econ_{k}":v for k,v in dry_gas_composition(o2_econ,ea14,carbon_burned_pct,f).items()})
    vals.update({f"ah_{k}":v for k,v in dry_gas_composition(o2_ah,ea15,carbon_burned_pct,f).items()})
    return ModuleResult(vals)
