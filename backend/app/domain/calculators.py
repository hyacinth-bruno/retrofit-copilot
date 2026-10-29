"""Deterministic retrofit maths.

Design rule: the model decides *what* to recommend; this module calculates *how much*.
No LLM ever produces a cost, subsidy or CO2 number that reaches the user.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.schemas import BuildingProfile

FOSSIL = {"gas", "oil"}


@lru_cache
def reference(path: str | None = None) -> dict:
    p = Path(path) if path else get_settings().data_dir / "reference" / "retrofit_reference.json"
    return json.loads(p.read_text(encoding="utf-8"))


def energy_class_for(kwh_m2a: float) -> str:
    for label, upper in reference()["energy_classes_kwh_m2a"]:
        if kwh_m2a < upper:
            return label
    return "H"


def _units(profile: BuildingProfile) -> int:
    return max(1, profile.dwelling_units or 1)


def _area(profile: BuildingProfile) -> float:
    return float(profile.living_area_m2 or 0)


@dataclass
class MeasureEstimate:
    measure_id: str
    label: str
    category: str
    quantity: float
    unit: str
    cost_low: float
    cost_high: float
    saving_pct: float  # midpoint, applied to final energy
    notes: str

    @property
    def cost_mid(self) -> float:
        return round((self.cost_low + self.cost_high) / 2, -2)

    def as_dict(self) -> dict:
        return {
            "measure_id": self.measure_id,
            "label": self.label,
            "category": self.category,
            "quantity": round(self.quantity, 1),
            "unit": self.unit,
            "cost_eur_low": round(self.cost_low, -2),
            "cost_eur_high": round(self.cost_high, -2),
            "cost_eur": self.cost_mid,
            "saving_pct": self.saving_pct,
            "notes": self.notes,
        }


def estimate_measure(
    measure_id: str, profile: BuildingProfile, heat_demand_kwh_m2a: float | None = None
) -> MeasureEstimate:
    """Cost range and saving for one measure. `heat_demand_kwh_m2a` lets the heat pump be
    sized on the demand left after envelope measures instead of today's demand."""
    cfg = reference()["measures"].get(measure_id)
    if cfg is None:
        raise ValueError(f"Unknown measure '{measure_id}'")
    area = _area(profile)
    units = _units(profile)
    saving = sum(cfg["saving_pct"]) / 2
    notes = ""

    if "area_factor" in cfg:
        qty = area * cfg["area_factor"]
        lo, hi = (qty * c for c in cfg["cost_per_unit_eur"])
        notes = f"Assumes {cfg['area_factor']} {cfg['unit']} per m² living area."
    elif measure_id == "ventilation_heat_recovery":
        qty = units
        lo, hi = (units * c for c in cfg["cost_per_dwelling_eur"])
    elif measure_id == "heat_pump":
        demand = (
            heat_demand_kwh_m2a
            if heat_demand_kwh_m2a is not None
            else (profile.final_energy_kwh_m2a or 0)
        )
        heat_kwh = area * demand * cfg["boiler_efficiency"]
        qty = max(5.0, heat_kwh / cfg["full_load_hours"])
        lo, hi = (max(cfg["min_cost_eur"], qty * c) for c in cfg["cost_per_kw_eur"])
        notes = (
            "Sized on the heat demand after the envelope measures in this plan."
            if heat_demand_kwh_m2a is not None
            else "Sized on today's heat demand; envelope measures first allow a smaller unit."
        )
    elif measure_id == "pv":
        qty = min(cfg["max_kwp"], area * cfg["kwp_per_m2_living"])
        lo, hi = (qty * c for c in cfg["cost_per_kwp_eur"])
        notes = "Grid-connected; tenant electricity model not included."
    else:  # pragma: no cover
        raise ValueError(measure_id)

    return MeasureEstimate(
        measure_id, cfg["label"], cfg["category"], qty, cfg["unit"], lo, hi, saving, notes
    )


def eligible_cap(caps: dict, units: int) -> float:
    return (
        caps["first_unit"]
        + caps["units_2_to_6"] * min(max(units - 1, 0), 5)
        + caps["unit_7_plus"] * max(units - 6, 0)
    )


def estimate_set(measure_ids: list[str], profile: BuildingProfile) -> list[MeasureEstimate]:
    """Estimate a set of measures, sizing the heat pump after the envelope savings."""
    others = [estimate_measure(m, profile) for m in measure_ids if m != "heat_pump"]
    if "heat_pump" not in measure_ids:
        return others
    remaining = profile.final_energy_kwh_m2a or 0.0
    for e in others:
        remaining *= 1 - e.saving_pct / 100
    hp = estimate_measure("heat_pump", profile, heat_demand_kwh_m2a=remaining)
    order = {m: i for i, m in enumerate(measure_ids)}
    return sorted([*others, hp], key=lambda e: order[e.measure_id])


def subsidies(
    estimates: list[MeasureEstimate],
    profile: BuildingProfile,
    *,
    owner_occupied: bool = False,
    has_isfp: bool = False,
) -> dict[str, dict]:
    """Return subsidy per measure id. Caps apply per building and calendar year, per programme."""
    ref = reference()["subsidies"]
    units = _units(profile)
    out: dict[str, dict] = {}

    # BAFA: envelope + plant share one cap
    bafa = ref["bafa_envelope_and_plant"]
    bafa_items = [e for e in estimates if e.category in ("envelope", "plant")]
    bafa_cost = sum(e.cost_mid for e in bafa_items)
    cap_without = eligible_cap(bafa["caps_without_isfp"], units)
    cap_with = eligible_cap(bafa["caps_with_isfp"], units)
    if has_isfp:
        eligible = min(bafa_cost, cap_with)
        bafa_total = bafa["base_rate"] * eligible + bafa["isfp_bonus_rate"] * max(
            0.0, eligible - cap_without
        )
    else:
        eligible = min(bafa_cost, cap_without)
        bafa_total = bafa["base_rate"] * eligible
    for e in bafa_items:
        share = e.cost_mid / bafa_cost if bafa_cost else 0
        out[e.measure_id] = {
            "subsidy_eur": round(bafa_total * share, -1),
            "program": bafa["program"],
        }

    # KfW heating
    kfw = ref["kfw_heating"]
    for e in estimates:
        if e.category != "heating":
            continue
        rate = kfw["base_rate"]
        if owner_occupied and profile.heating_type in FOSSIL:
            rate += kfw["speed_bonus_rate"]
        rate = min(rate, kfw["max_rate"])
        eligible = min(e.cost_mid, eligible_cap(kfw["caps"], units))
        out[e.measure_id] = {"subsidy_eur": round(rate * eligible, -1), "program": kfw["program"]}

    for e in estimates:
        out.setdefault(e.measure_id, {"subsidy_eur": 0.0, "program": ref["none"]["program"]})
    return out


def energy_after(estimates: list[MeasureEstimate], profile: BuildingProfile) -> tuple[float, str]:
    """Final energy after measures (kWh/m²a) and the resulting main energy carrier."""
    ref = reference()["measures"]
    before = profile.final_energy_kwh_m2a or 0.0
    after = before
    for e in estimates:
        after *= 1 - e.saving_pct / 100
    carrier = profile.heating_type
    ids = {e.measure_id for e in estimates}
    if "heat_pump" in ids:
        hp = ref["heat_pump"]
        after = after * hp["boiler_efficiency"] / hp["scop"]
        carrier = "heat_pump"
    return round(after, 1), carrier


def co2_tonnes(kwh_m2a: float, area: float, carrier: str) -> float:
    factor = reference()["co2_factors_kg_per_kwh"].get(carrier, 0.30)
    return round(kwh_m2a * area * factor / 1000, 1)


def pv_offset_tonnes(estimates: list[MeasureEstimate]) -> float:
    pv = next((e for e in estimates if e.measure_id == "pv"), None)
    if not pv:
        return 0.0
    cfg = reference()["measures"]["pv"]
    kwh = pv.quantity * cfg["yield_kwh_per_kwp"] * cfg["self_consumption_share"]
    return round(kwh * reference()["co2_factors_kg_per_kwh"]["electric"] / 1000, 1)


def max_rent_increase(net_modernisation_cost: float, area: float) -> float | None:
    """§ 559 BGB: 8 % of modernisation cost per year, capped at 3 €/m² per month (simplified)."""
    if area <= 0:
        return None
    levy = reference()["modernisation_levy"]
    per_m2_month = net_modernisation_cost * levy["annual_rate"] / 12 / area
    return round(min(per_m2_month, levy["cap_eur_m2_month"]), 2)


def round_eur(x: float) -> float:
    return float(math.floor(x / 100 + 0.5) * 100)
