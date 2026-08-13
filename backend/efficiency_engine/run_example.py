from pathlib import Path
from boiler_efficiency.io_json import run_json
base=Path(__file__).parent
result=run_json(base/'D:/Projects/Code/Calculations/Download the modular Python code package/boiler_efficiency_python/examples/mundra_appendix_d4.json',base/'D:/Projects/Code/Calculations/Download the modular Python code package/boiler_efficiency_python/examples/mundra_result.json')
print(f"HHV efficiency: {result['efficiency']['values']['boiler_efficiency_hhv_pct']:.3f}%")
print(f"Corrected HHV efficiency: {result['corrections']['values']['corrected_boiler_efficiency_hhv_pct']:.3f}%")
print(f"Air-heater leakage: {result['air_flue_gas']['values']['air_heater_leakage_pct']:.3f}%")
print(
    f"Boiler Duty: "
    f"{result['boiler_duty']['values']['boiler_duty_mw']:.3f} MW"
)
print(
    f"Dulong HHV: "
    f"{result['gcv_check']['values']['dulong_hhv_kcal_kg']:.2f} kcal/kg"
)
print(
    f"Fuel Firing: "
    f"{result['fuel_firing']['values']['fuel_firing_kg_s']:.3f} kg/s"
)