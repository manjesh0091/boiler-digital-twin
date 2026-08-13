"""JSON input/output convenience layer."""
import json
from pathlib import Path
from .models import FuelAnalysis,RefuseAnalysis,AmbientConditions,GasMeasurements,EnthalpyInputs,EfficiencyAssumptions,BoilerDutyInputs,GCVCheckInputs
from .orchestrator import run_energy_balance

def run_json(input_path, output_path):
    d = json.loads(Path(input_path).read_text())
    result=run_energy_balance(FuelAnalysis(**d["fuel"]),RefuseAnalysis(**d["refuse"]),
      AmbientConditions(**d["ambient"]),GasMeasurements(**d["gas"]),
      EnthalpyInputs(**d["enthalpy"]),EfficiencyAssumptions(**d.get("assumptions",{})),BoilerDutyInputs(**d["boiler_duty"]),GCVCheckInputs(**d["gcv_check"]))
    Path(output_path).write_text(json.dumps(result,indent=2))
    return result
