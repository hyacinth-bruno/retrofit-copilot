"""The agent graph with scripted model responses: no API key needed."""

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agent import planner
from app.observability.tracer import start_run
from app.schemas import BuildingProfile, DraftMeasure, PlanDraft, PlanRequest

REQ = PlanRequest(
    profile=BuildingProfile(
        building_type="multi_family",
        year_built=1968,
        dwelling_units=8,
        living_area_m2=712,
        final_energy_kwh_m2a=187.3,
        energy_class="F",
        heating_type="gas",
    )
)


def scripted_agent():
    turns = iter(
        [
            AIMessage(
                "",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "BAFA envelope grant"},
                        "id": "t1",
                    }
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "name": "estimate_outcome",
                        "args": {"measure_ids": ["facade_insulation", "heat_pump"]},
                        "id": "t2",
                    }
                ],
            ),
            AIMessage("I have enough information."),
        ]
    )
    return RunnableLambda(lambda _msgs: next(turns))


def test_agent_plan_numbers_come_from_code_and_citations_are_checked():
    draft = PlanDraft(
        summary="Insulate the facade, then switch to a heat pump.",
        measures=[
            DraftMeasure(
                measure_id="heat_pump",
                priority=2,
                rationale="Replace gas.",
                citation_ids=["beg-em-heating#1", "made-up#9"],
            ),
            DraftMeasure(
                measure_id="facade_insulation",
                priority=1,
                rationale="Uninsulated 1968 walls.",
                citation_ids=["beg-em-envelope#1"],
            ),
        ],
        confidence=0.8,
    )
    with start_run("test_plan") as run:
        plan = planner.plan(
            REQ, run, llm_tools=scripted_agent(), llm_final=RunnableLambda(lambda _m: draft)
        )
    assert plan.planner == "agent"
    assert [m.measure_id for m in plan.measures] == ["facade_insulation", "heat_pump"]
    assert all("made-up#9" not in m.citation_ids for m in plan.measures)
    assert any(i.code == "invalid_citation" for i in plan.issues)
    assert plan.total_cost_eur > plan.total_subsidy_eur > 0
    assert plan.co2_after_t < plan.co2_before_t
    tool_spans = [s.name for s in run.spans if s.kind in ("tool", "retrieval")]
    assert tool_spans == ["search_knowledge", "estimate_outcome"]


def test_without_key_rule_based_fallback_is_used():
    with start_run("test_plan") as run:
        plan = planner.plan(REQ, run)
    assert plan.planner == "rule_based_fallback"
    assert plan.needs_review and run.fallback_used
    assert "heat_pump" in [m.measure_id for m in plan.measures]
