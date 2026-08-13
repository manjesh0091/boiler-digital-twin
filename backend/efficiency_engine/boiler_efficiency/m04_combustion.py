"""M04 - ASME-style refuse and combustion calculations."""
from .models import FuelAnalysis, RefuseAnalysis, ModuleResult

def calculate_refuse(f: FuelAnalysis, r: RefuseAnalysis) -> ModuleResult:
    if abs(
        r.bed_ash_distribution_pct +
        r.cyclone_ash_distribution_pct +
        r.aph_ash_distribution_pct +
        r.esp_ash_distribution_pct -
        100
    ) > 0.1:
        raise ValueError("Ash distribution must total 100%")
    total_uc = (
        r.bed_ash_distribution_pct * r.bed_ash_unburned_carbon_pct +
        r.cyclone_ash_distribution_pct * r.cyclone_ash_unburned_carbon_pct +
        r.aph_ash_distribution_pct * r.aph_ash_unburned_carbon_pct +
        r.esp_ash_distribution_pct * r.esp_ash_unburned_carbon_pct
    ) / 100.0
    residue = f.ash_pct/(100.0-total_uc)
    unburned = total_uc*residue/100.0       # kg C/kg fuel
    carbon_burned_pct = f.carbon_pct-unburned*100.0
    return ModuleResult({
        "total_unburned_carbon_in_refuse_pct": total_uc,
        "residue_kg_kg_fuel": residue,
        "unburned_carbon_kg_kg_fuel": unburned,
        "carbon_burned_pct": carbon_burned_pct,

        "bed_ash_distribution_pct": r.bed_ash_distribution_pct,
        "cyclone_ash_distribution_pct": r.cyclone_ash_distribution_pct,
        "aph_ash_distribution_pct": r.aph_ash_distribution_pct,
        "esp_ash_distribution_pct": r.esp_ash_distribution_pct,

        "bed_ash_temperature_c": r.bed_ash_temperature_c,
        "cyclone_ash_temperature_c": r.cyclone_ash_temperature_c,
        "aph_ash_temperature_c": r.aph_ash_temperature_c,
        "esp_ash_temperature_c": r.esp_ash_temperature_c,
    })

def theoretical_air_kg_kg(carbon_burned_pct: float, f: FuelAnalysis) -> float:
    return (0.1151*carbon_burned_pct + 0.3429*f.hydrogen_pct +
            0.0431*f.sulfur_pct - 0.0432*f.oxygen_pct)

def excess_air_from_o2(o2_dry_pct: float, carbon_burned_pct: float, f: FuelAnalysis):
    th_air=theoretical_air_kg_kg(carbon_burned_pct,f)
    mo_th=th_air/28.9625
    mo_products=(carbon_burned_pct/1201.1 + f.sulfur_pct/3206.5 + f.nitrogen_pct/2801.34)
    ea=100.0*o2_dry_pct*(mo_products+0.7905*mo_th)/(mo_th*(20.95-o2_dry_pct))
    return ea,mo_th,mo_products

def dry_gas_composition(o2_dry_pct, ea_pct, carbon_burned_pct, f):
    th_air=theoretical_air_kg_kg(carbon_burned_pct,f); mo_th=th_air/28.9625
    mo_products=(carbon_burned_pct/1201.1 + f.sulfur_pct/3206.5 + f.nitrogen_pct/2801.34)
    mo_dry=mo_products+mo_th*(0.7905+ea_pct/100.0)
    co2=(carbon_burned_pct/12.011)/mo_dry
    so2=(f.sulfur_pct/32.065)/mo_dry
    n2_f=(f.nitrogen_pct/28.0134)/mo_dry
    n2_air=100.0-o2_dry_pct-co2-so2-n2_f
    return {"dry_gas_mol_kg_fuel":mo_dry,"o2_dry_vol_pct":o2_dry_pct,
            "co2_dry_vol_pct":co2,"so2_dry_vol_pct":so2,
            "fuel_n2_dry_vol_pct":n2_f,"air_n2_dry_vol_pct":n2_air}
