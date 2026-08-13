"""Common engineering validation rules."""
from .models import FuelAnalysis

def require_range(name: str, value: float, lo: float, hi: float) -> None:
    if not lo <= value <= hi:
        raise ValueError(f"{name}={value} outside [{lo}, {hi}]")

def validate_fuel(fuel: FuelAnalysis, closure_tolerance_pct: float = 1.0):
    warnings = []
    for name in ("carbon_pct", "hydrogen_pct", "oxygen_pct", "nitrogen_pct",
                 "sulfur_pct", "ash_pct", "moisture_pct"):
        require_range(name, getattr(fuel, name), 0.0, 100.0)
    if fuel.hhv_kj_kg <= 0:
        raise ValueError("HHV must be positive")
    error = fuel.total_pct() - 100.0
    if abs(error) > closure_tolerance_pct:
        raise ValueError(f"Ultimate analysis closure error {error:.3f} %-point")
    if abs(error) > 0.1:
        warnings.append(f"Ultimate analysis closure is {fuel.total_pct():.3f}%")
    return warnings
