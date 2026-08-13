"""M05 - Ambient-air moisture."""
import math
from .models import AmbientConditions, ModuleResult

def saturation_pressure_bar(temp_c: float) -> float:
    # Buck equation, suitable for normal ambient temperatures.
    return 0.0061121*math.exp((18.678-temp_c/234.5)*(temp_c/(257.14+temp_c)))

def humidity_ratio(a: AmbientConditions) -> ModuleResult:
    if not 0 <= a.relative_humidity_pct <= 100: raise ValueError("RH outside 0-100%")
    pws=saturation_pressure_bar(a.dry_bulb_c)
    pv=a.relative_humidity_pct/100.0*pws
    if a.pressure_bar_a <= pv: raise ValueError("Ambient pressure must exceed vapor pressure")
    w=0.622*pv/(a.pressure_bar_a-pv)
    return ModuleResult({"saturation_pressure_bar":pws,"vapor_partial_pressure_bar":pv,
                         "humidity_ratio_kg_kg_dry_air":w,
                         "water_fraction_kg_kg_wet_air":w/(1+w)})
