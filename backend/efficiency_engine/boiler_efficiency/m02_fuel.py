"""M02 - Fuel basis conversion and flow-weighted blending."""
from typing import Sequence, Tuple
from .models import FuelAnalysis, ModuleResult
from .validation import validate_fuel

def dry_to_as_fired(dry: FuelAnalysis, moisture_as_fired_pct: float, hhv_as_fired_kj_kg: float) -> FuelAnalysis:
    factor = (100.0 - moisture_as_fired_pct) / 100.0
    return FuelAnalysis(
        dry.carbon_pct*factor, dry.hydrogen_pct*factor, dry.oxygen_pct*factor,
        dry.nitrogen_pct*factor, dry.sulfur_pct*factor, dry.ash_pct*factor,
        moisture_as_fired_pct, hhv_as_fired_kj_kg,
        name=f"{dry.name} (as fired)"
    )

def blend_fuels(fuels_and_flows: Sequence[Tuple[FuelAnalysis, float]]) -> Tuple[FuelAnalysis, ModuleResult]:
    if not fuels_and_flows:
        raise ValueError("At least one fuel is required")
    total = sum(flow for _, flow in fuels_and_flows)
    if total <= 0:
        raise ValueError("Total fuel flow must be positive")
    warnings = []
    for fuel, flow in fuels_and_flows:
        if flow < 0: raise ValueError("Fuel flow cannot be negative")
        warnings += validate_fuel(fuel)
    def w(attr): return sum(getattr(f, attr)*m for f,m in fuels_and_flows)/total
    blend = FuelAnalysis(w("carbon_pct"), w("hydrogen_pct"), w("oxygen_pct"),
                         w("nitrogen_pct"), w("sulfur_pct"), w("ash_pct"),
                         w("moisture_pct"), w("hhv_kj_kg"), name="Blended fuel")
    values = {"total_fuel_flow_kg_s": total, "analysis_total_pct": blend.total_pct()}
    values.update({f"blend_{k}": v for k,v in blend.__dict__.items() if isinstance(v,(int,float))})
    return blend, ModuleResult(values, warnings)
    

def normalize_fuel(fuel: FuelAnalysis) -> FuelAnalysis:
    total = (
        fuel.carbon_pct
        + fuel.hydrogen_pct
        + fuel.oxygen_pct
        + fuel.nitrogen_pct
        + fuel.sulfur_pct
        + fuel.ash_pct
        + fuel.moisture_pct
    )

    if total <= 0:
        raise ValueError("Fuel analysis total must be positive")

    if abs(total - 100.0) < 0.001:
        return fuel

    factor = 100.0 / total

    return FuelAnalysis(
        carbon_pct=fuel.carbon_pct * factor,
        hydrogen_pct=fuel.hydrogen_pct * factor,
        oxygen_pct=fuel.oxygen_pct * factor,
        nitrogen_pct=fuel.nitrogen_pct * factor,
        sulfur_pct=fuel.sulfur_pct * factor,
        ash_pct=fuel.ash_pct * factor,
        moisture_pct=fuel.moisture_pct * factor,
        hhv_kj_kg=fuel.hhv_kj_kg,
        volatile_matter_pct=fuel.volatile_matter_pct,
        fixed_carbon_pct=fuel.fixed_carbon_pct,
        name=fuel.name,
)
