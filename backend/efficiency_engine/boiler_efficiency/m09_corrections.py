"""M09 - Contract/design correction correlations from supplied Appendix D-4."""
from .models import FuelAnalysis, ModuleResult

def appendix_d4_corrections(efficiency_pct, fan_inlet_air_c, humidity_ratio, fuel: FuelAnalysis):
    c1=0.006*fan_inlet_air_c-0.192
    c2=-7*humidity_ratio+0.1806
    c3=-0.048*fuel.moisture_pct+0.72
    c4=-1.06*fuel.hydrogen_pct+4.1022
    c5=0.000385*fuel.hhv_kj_kg-9.118725
    s=c1+c2+c3+c4+c5
    return ModuleResult({"air_temperature_correction_pct":c1,"air_humidity_correction_pct":c2,
      "fuel_moisture_correction_pct":c3,"fuel_hydrogen_correction_pct":c4,
      "fuel_hhv_correction_pct":c5,"sum_correction_pct":s,
      "corrected_boiler_efficiency_hhv_pct":efficiency_pct-s})
