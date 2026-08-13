"""M01 - Boiler duty from stream mass flows."""

from typing import Mapping, Tuple
from .models import ModuleResult


def stream_heat_mw(
    mass_flow_kg_s: float,
    enthalpy_kj_kg: float,
) -> float:

    if mass_flow_kg_s < 0:
        raise ValueError("Mass flow cannot be negative")

    return mass_flow_kg_s * enthalpy_kj_kg / 1000.0


def calculate_boiler_duty(
    heat_leaving_streams: Mapping[str, Tuple[float, float]],
    heat_entering_streams: Mapping[str, Tuple[float, float]],
) -> ModuleResult:

    q_out = {
        k: stream_heat_mw(*v)
        for k, v in heat_leaving_streams.items()
    }

    q_in = {
        k: stream_heat_mw(*v)
        for k, v in heat_entering_streams.items()
    }

    duty = sum(q_out.values()) - sum(q_in.values())

    if duty <= 0:
        raise ValueError("Calculated boiler duty must be positive")

    return ModuleResult(
        {
            "heat_leaving_mw": sum(q_out.values()),
            "heat_entering_mw": sum(q_in.values()),
            "boiler_duty_mw": duty,
            "boiler_duty_kcal_h": duty * 860000.0,
            **{f"q_out_{k}_mw": v for k, v in q_out.items()},
            **{f"q_in_{k}_mw": v for k, v in q_in.items()},
        }
    )