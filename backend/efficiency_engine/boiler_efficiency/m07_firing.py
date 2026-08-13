"""M07 - Fuel firing from boiler duty and current efficiency."""
from .models import ModuleResult

def calculate_firing(boiler_duty_mw: float, hhv_kj_kg: float, efficiency_pct: float, air_kg_kg_fuel: float):
    if not 0 < efficiency_pct <= 100: raise ValueError("Efficiency must be in (0,100]")
    fuel_kg_s=boiler_duty_mw*1000.0/(hhv_kj_kg*efficiency_pct/100.0)
    return ModuleResult({"fuel_firing_kg_s":fuel_kg_s,"fuel_firing_kg_h":fuel_kg_s*3600,
                         "air_flow_kg_s":fuel_kg_s*air_kg_kg_fuel,
                         "fuel_heat_input_mw":fuel_kg_s*hhv_kj_kg/1000})
