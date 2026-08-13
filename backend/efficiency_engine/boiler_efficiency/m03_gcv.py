"""M03 - Dulong HHV check and optional composition correction."""
from dataclasses import replace
from .models import FuelAnalysis, ModuleResult

def dulong_hhv_kcal_kg(f: FuelAnalysis) -> float:
    # Percent inputs; divide the classic expression by 100.
    return (8080*f.carbon_pct + 34500*(f.hydrogen_pct-f.oxygen_pct/8.0) + 2240*f.sulfur_pct)/100.0

def validate_and_correct(f: FuelAnalysis, lower: float=0.95, upper: float=1.04,
                         apply_correction: bool=False):
    measured_kcal = f.hhv_kj_kg / 4.1868
    calculated = dulong_hhv_kcal_kg(f)
    g = calculated/measured_kcal
    warnings=[]
    corrected=f
    required = not (lower <= g <= upper)
    if required:
        warnings.append(f"Dulong/Measured HHV factor {g:.4f} outside [{lower}, {upper}]")
    if required and apply_correction:
        # Implements the supplied write-up literally; retain original data separately.
        c,h,o,n,s,m = [x*g for x in (f.carbon_pct,f.hydrogen_pct,f.oxygen_pct,
                                     f.nitrogen_pct,f.sulfur_pct,f.moisture_pct)]
        ash = 100.0-(c+h+o+n+s+m)
        if ash < 0: raise ValueError("G-factor correction creates negative ash")
        corrected=replace(f, carbon_pct=c, hydrogen_pct=h, oxygen_pct=o,
                          nitrogen_pct=n, sulfur_pct=s, moisture_pct=m, ash_pct=ash)
    return corrected, ModuleResult({"dulong_hhv_kcal_kg":calculated,
        "measured_hhv_kcal_kg":measured_kcal,"g_factor":g,
        "correction_required":float(required),"correction_applied":float(required and apply_correction)},warnings)
