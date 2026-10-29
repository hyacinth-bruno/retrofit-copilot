"""Typed contracts shared by extraction, planning, the API and the evals."""

from typing import Literal

from pydantic import BaseModel, Field

EnergyClass = Literal["A+", "A", "B", "C", "D", "E", "F", "G", "H"]
HeatingType = Literal[
    "gas", "oil", "district_heating", "heat_pump", "electric", "biomass", "other", "unknown"
]
BuildingType = Literal["single_family", "multi_family", "non_residential", "unknown"]
MeasureId = Literal[
    "facade_insulation",
    "roof_insulation",
    "top_floor_ceiling_insulation",
    "basement_ceiling_insulation",
    "windows",
    "heat_pump",
    "ventilation_heat_recovery",
    "pv",
]

PROFILE_FIELDS = [
    "address",
    "building_type",
    "year_built",
    "dwelling_units",
    "living_area_m2",
    "final_energy_kwh_m2a",
    "energy_class",
    "heating_type",
    "certificate_type",
]
CRITICAL_FIELDS = ["year_built", "living_area_m2", "final_energy_kwh_m2a", "heating_type"]


# ---------- Extraction ----------


class FieldEvidence(BaseModel):
    field: str = Field(description="Name of the profile field this evidence supports.")
    quote: str = Field(description="Short text copied exactly from the document.")
    confidence: float = Field(ge=0, le=1, description="How sure you are about this value, 0 to 1.")


class BuildingProfile(BaseModel):
    """Key facts about a building, as read from an energy certificate (Energieausweis)."""

    address: str | None = Field(None, description="Street, number, postcode and city.")
    building_type: BuildingType = "unknown"
    year_built: int | None = Field(None, description="Baujahr Gebäude.")
    dwelling_units: int | None = Field(None, description="Anzahl Wohnungen.")
    living_area_m2: float | None = Field(
        None, description="Gebäudenutzfläche (AN) or Wohnfläche in m²."
    )
    final_energy_kwh_m2a: float | None = Field(
        None, description="Endenergiebedarf or Endenergieverbrauch in kWh/(m²·a)."
    )
    energy_class: EnergyClass | None = Field(None, description="Energieeffizienzklasse A+ to H.")
    heating_type: HeatingType = "unknown"
    certificate_type: Literal["demand", "consumption", "unknown"] = Field(
        "unknown", description="Bedarfsausweis = demand, Verbrauchsausweis = consumption."
    )
    evidence: list[FieldEvidence] = Field(
        default_factory=list, description="One entry per field you filled in."
    )


class Issue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    field: str | None = None


class ExtractionResult(BaseModel):
    run_id: str
    profile: BuildingProfile
    issues: list[Issue]
    needs_review: bool
    mode: Literal["text", "vision", "regex_fallback", "none"]
    model: str | None = None
    cached: bool = False


# ---------- Planning ----------


class DraftMeasure(BaseModel):
    measure_id: MeasureId
    priority: int = Field(ge=1, le=10, description="1 = do first.")
    rationale: str = Field(description="One or two sentences, specific to this building.")
    citation_ids: list[str] = Field(
        default_factory=list, description="chunk ids from search_knowledge that support this."
    )


class PlanDraft(BaseModel):
    """What the model decides. All numbers are calculated afterwards in code."""

    summary: str = Field(description="Three sentences maximum, plain English.")
    measures: list[DraftMeasure]
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class Citation(BaseModel):
    chunk_id: str
    title: str
    url: str | None = None
    snippet: str


class PlannedMeasure(BaseModel):
    measure_id: MeasureId
    label: str
    category: str
    priority: int
    rationale: str
    cost_eur_low: float
    cost_eur_high: float
    cost_eur: float
    subsidy_eur: float
    subsidy_program: str
    saving_pct: float
    citation_ids: list[str]


class RetrofitPlan(BaseModel):
    run_id: str
    summary: str
    measures: list[PlannedMeasure]
    total_cost_eur: float
    total_subsidy_eur: float
    net_cost_eur: float
    energy_before_kwh_m2a: float
    energy_after_kwh_m2a: float
    energy_class_before: str | None
    energy_class_after: str
    co2_before_t: float
    co2_after_t: float
    max_rent_increase_eur_m2_month: float | None
    assumptions: list[str]
    citations: list[Citation]
    issues: list[Issue]
    needs_review: bool
    planner: Literal["agent", "rule_based_fallback"]
    steps: list[dict]


class PlanRequest(BaseModel):
    profile: BuildingProfile
    owner_occupied: bool = False
    has_isfp: bool = False


# ---------- Q&A ----------


class AnswerDraft(BaseModel):
    answer: str = Field(description="Plain English, at most 120 words.")
    citation_ids: list[str] = Field(description="chunk ids that support the answer.")
    answerable: bool = Field(description="False if the sources do not contain the answer.")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskResponse(BaseModel):
    run_id: str
    answer: str
    citations: list[Citation]
    answerable: bool
    mode: Literal["llm", "extractive_fallback", "refused"]
    issues: list[Issue]


class Feedback(BaseModel):
    run_id: str
    field: str
    predicted: str | None = None
    corrected: str
