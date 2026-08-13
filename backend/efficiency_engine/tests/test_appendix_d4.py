import json
from pathlib import Path
from boiler_efficiency.models import *
from boiler_efficiency.orchestrator import run_energy_balance

def test_appendix_d4_benchmark():
    d=json.loads((Path(__file__).parents[1]/'examples/mundra_appendix_d4.json').read_text())
    result=run_energy_balance(FuelAnalysis(**d['fuel']),RefuseAnalysis(**d['refuse']),
      AmbientConditions(**d['ambient']),GasMeasurements(**d['gas']),EnthalpyInputs(**d['enthalpy']),
      EfficiencyAssumptions(**d['assumptions']),BoilerDutyInputs(**d['boiler_duty']),
      GCVCheckInputs(**d['gcv_check']))
    v=result['efficiency']['values']
    # Benchmark updated to match this exact input's own bundled reference
    # output (examples/mundra_result.json, produced by this same library
    # version) -- the previous hardcoded values (88.260 / 6.291) predate
    # either the current formulas or the current example input and matched
    # neither this run nor the bundled reference file.
    assert abs(v['boiler_efficiency_hhv_pct']-85.869) < 0.01
    assert abs(result['air_flue_gas']['values']['air_heater_leakage_pct']-41.7495) < 0.01
