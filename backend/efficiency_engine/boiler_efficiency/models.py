"""Typed data models used by the boiler-efficiency modules."""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

@dataclass(frozen=True)
class FuelAnalysis:
    carbon_pct: float
    hydrogen_pct: float
    oxygen_pct: float
    nitrogen_pct: float
    sulfur_pct: float
    ash_pct: float
    moisture_pct: float
    hhv_kj_kg: float
    volatile_matter_pct: Optional[float] = None
    fixed_carbon_pct: Optional[float] = None
    name: str = "Fuel"

    def total_pct(self) -> float:
        return (self.carbon_pct + self.hydrogen_pct + self.oxygen_pct +
                self.nitrogen_pct + self.sulfur_pct + self.ash_pct +
                self.moisture_pct)

@dataclass(frozen=True)
class RefuseAnalysis:
    bed_ash_distribution_pct: float
    cyclone_ash_distribution_pct: float
    aph_ash_distribution_pct: float
    esp_ash_distribution_pct: float

    bed_ash_unburned_carbon_pct: float
    cyclone_ash_unburned_carbon_pct: float
    aph_ash_unburned_carbon_pct: float
    esp_ash_unburned_carbon_pct: float

    bed_ash_temperature_c: float = 1100.0
    cyclone_ash_temperature_c: float = 400.0
    aph_ash_temperature_c: float = 135.0
    esp_ash_temperature_c: float = 135.0

@dataclass(frozen=True)
class AmbientConditions:
    dry_bulb_c: float
    pressure_bar_a: float
    relative_humidity_pct: float
    fuel_temp_c: float


    
@dataclass(frozen=True)
class GasMeasurements:
    o2_economizer_outlet_dry_pct: float
    o2_air_heater_outlet_dry_pct: float
    flue_gas_specific_heat_cpg_btu_lbm_f: float
    gas_temp_air_heater_inlet_c: float
    gas_temp_air_heater_outlet_c: float
    air_temp_air_heater_inlet_c: float
    air_temp_fan_inlet_c: Optional[float] = None

@dataclass(frozen=True)
class EnthalpyInputs:
    reference_water_temperature_c: float

@dataclass(frozen=True)
class EfficiencyAssumptions:
    surface_radiation_loss_pct: float = 0.18
    other_loss_pct: float = 0.25
    auxiliary_power_credit_pct: float = 0.0
    additional_moisture_kg_kg_fuel: float = 0.0
    hydrogen_to_water_factor: float = 8.937
    unburned_carbon_heating_value_kj_kg: float = 33700.0
    spent_sorbent_lbm_per_100_lbm_fuel: float = 0.0

@dataclass
class BoilerDutyInputs:
    MAIN_STEAM_FLOW: float
    MAIN_STEAM_PRESSURE: float
    MAIN_STEAM_TEMPERATURE: float
    FEEDWATER_FLOW: float
    FW_PR_TO_FCS: float
    FEEDWATER_TEMP_TO_FCS: float   

@dataclass
class GCVCheckInputs:
    lower: float = 0.95
    upper: float = 1.04
    apply_correction: bool = False    

@dataclass
class ModuleResult:
    values: Dict[str, float]
    warnings: List[str] = field(default_factory=list)
    status: str = "VALID"

    def to_dict(self):
        return {"status": self.status, "values": self.values, "warnings": self.warnings}
