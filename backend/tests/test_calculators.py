from app.domain import calculators as calc
from app.schemas import BuildingProfile

MFH = BuildingProfile(
    building_type="multi_family",
    year_built=1968,
    dwelling_units=8,
    living_area_m2=712,
    final_energy_kwh_m2a=187.3,
    energy_class="F",
    heating_type="gas",
)


def test_caps_match_official_example():
    # Reform summary: 8 dwelling units -> 121,000 EUR without iSFP, 240,000 EUR with iSFP
    ref = calc.reference()["subsidies"]["bafa_envelope_and_plant"]
    assert calc.eligible_cap(ref["caps_without_isfp"], 8) == 121_000
    assert calc.eligible_cap(ref["caps_with_isfp"], 8) == 240_000


def test_energy_classes():
    assert calc.energy_class_for(29) == "A+"
    assert calc.energy_class_for(187.3) == "F"
    assert calc.energy_class_for(260) == "H"


def test_isfp_bonus_only_above_cap_without_isfp():
    small = BuildingProfile(
        dwelling_units=1, living_area_m2=100, final_energy_kwh_m2a=150, heating_type="gas"
    )
    ests = [calc.estimate_measure("top_floor_ceiling_insulation", small)]
    without = calc.subsidies(ests, small, has_isfp=False)
    with_isfp = calc.subsidies(ests, small, has_isfp=True)
    # Under 30,000 EUR the iSFP bonus adds nothing after the July 2026 reform
    assert without == with_isfp


def test_landlord_gets_base_heating_rate_owner_gets_speed_bonus():
    hp = [calc.estimate_measure("heat_pump", MFH)]
    landlord = calc.subsidies(hp, MFH)["heat_pump"]["subsidy_eur"]
    owner = calc.subsidies(hp, MFH, owner_occupied=True)["heat_pump"]["subsidy_eur"]
    assert owner > landlord
    assert abs(owner / landlord - 0.46 / 0.30) < 0.01


def test_heat_pump_cuts_energy_and_co2():
    ests = [calc.estimate_measure(m, MFH) for m in ("facade_insulation", "heat_pump")]
    after, carrier = calc.energy_after(ests, MFH)
    assert carrier == "heat_pump"
    assert after < 187.3 / 3
    assert calc.co2_tonnes(after, 712, carrier) < calc.co2_tonnes(187.3, 712, "gas")


def test_rent_increase_is_capped():
    assert calc.max_rent_increase(10_000_000, 100) == 3.0
