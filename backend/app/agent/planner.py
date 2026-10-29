"""Retrofit planning agent (LangGraph).

Graph:   agent ──(tool calls?)──► tools ──► agent ... ──► finalize ──► END
                └──(done / limit)──────────────────────────┘

- agent:    Claude with three tools bound (search_knowledge, estimate_measures, estimate_outcome)
- tools:    runs the tool calls, records every retrieved chunk so citations can be checked
- finalize: Claude returns a PlanDraft (structured output): which measures, why, which sources
- assemble: plain Python recalculates every number and validates every citation

If the model is unavailable or the run goes over budget, a rule-based planner takes over.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.config import get_settings
from app.domain import calculators as calc
from app.llm import client
from app.observability.tracer import Run, callbacks_for
from app.rag.answer import to_citation
from app.rag.store import Hit, knowledge
from app.schemas import (
    BuildingProfile,
    DraftMeasure,
    Issue,
    PlanDraft,
    PlannedMeasure,
    PlanRequest,
    RetrofitPlan,
)

ALL_MEASURES = list(calc.reference()["measures"].keys())


class PlanState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    retrieved: Annotated[list[Hit], operator.add]
    iterations: int
    draft: PlanDraft | None


def build_tools(req: PlanRequest, run: Run) -> list:
    profile = req.profile

    @tool
    def search_knowledge(query: str) -> str:
        """Search the funding and retrofit knowledge base. Returns passages with chunk ids."""
        with run.span("search_knowledge", kind="retrieval", query=query) as sp:
            hits = knowledge().search(query)
            sp.meta["chunk_ids"] = [h.chunk_id for h in hits]
        payload = [
            {"chunk_id": h.chunk_id, "title": f"{h.title} — {h.section}", "text": h.text}
            for h in hits
        ]
        return json.dumps(
            {"results": payload, "_hits": [h.__dict__ for h in hits]}, ensure_ascii=False
        )

    @tool
    def estimate_measures(measure_ids: list[str]) -> str:
        """Cost range (EUR) and expected final-energy saving (%) for measures on this building.
        Valid ids: facade_insulation, roof_insulation, top_floor_ceiling_insulation,
        basement_ceiling_insulation, windows, heat_pump, ventilation_heat_recovery, pv."""
        with run.span("estimate_measures", kind="tool", measure_ids=measure_ids):
            out = []
            for m in measure_ids:
                try:
                    out.append(calc.estimate_measure(m, profile).as_dict())
                except ValueError as e:
                    out.append({"measure_id": m, "error": str(e)})
            return json.dumps(out)

    @tool
    def estimate_outcome(measure_ids: list[str]) -> str:
        """Subsidies, net cost, energy class and CO2 before and after for a set of measures."""
        with run.span("estimate_outcome", kind="tool", measure_ids=measure_ids):
            valid = [m for m in measure_ids if m in ALL_MEASURES]
            res = outcome(valid, req)
            res["estimates"] = [e.as_dict() for e in res["estimates"]]
            return json.dumps(res)

    return [search_knowledge, estimate_measures, estimate_outcome]


def outcome(measure_ids: list[str], req: PlanRequest) -> dict:
    p = req.profile
    ests = calc.estimate_set(measure_ids, p)
    subs = calc.subsidies(ests, p, owner_occupied=req.owner_occupied, has_isfp=req.has_isfp)
    before = p.final_energy_kwh_m2a or 0.0
    after, carrier = calc.energy_after(ests, p)
    area = float(p.living_area_m2 or 0)
    total = sum(e.cost_mid for e in ests)
    subsidy = sum(v["subsidy_eur"] for v in subs.values())
    co2_after = max(0.0, calc.co2_tonnes(after, area, carrier) - calc.pv_offset_tonnes(ests))
    return {
        "estimates": ests,
        "subsidies": subs,
        "total_cost_eur": total,
        "total_subsidy_eur": subsidy,
        "net_cost_eur": total - subsidy,
        "energy_before_kwh_m2a": before,
        "energy_after_kwh_m2a": after,
        "energy_class_before": p.energy_class,
        "energy_class_after": calc.energy_class_for(after) if after else "unknown",
        "co2_before_t": calc.co2_tonnes(before, area, p.heating_type),
        "co2_after_t": round(co2_after, 1),
    }


def profile_text(req: PlanRequest) -> str:
    p = req.profile.model_dump(exclude={"evidence"})
    return (
        f"Building profile:\n{json.dumps(p, ensure_ascii=False, indent=1)}\n"
        f"Owner-occupied: {req.owner_occupied}. Has an individual renovation roadmap (iSFP): {req.has_isfp}."
    )


def build_graph(req: PlanRequest, run: Run, llm_tools=None, llm_final=None):
    s = get_settings()
    tools = build_tools(req, run)
    by_name = {t.name: t for t in tools}
    llm_tools = llm_tools or client.with_tools(tools, name="planner")
    llm_final = llm_final or client.structured(PlanDraft, name="planner_finalize")
    cfg = {"callbacks": callbacks_for(run)}

    def agent(state: PlanState):
        msg = llm_tools.invoke(state["messages"], config=cfg)
        return {"messages": [msg], "iterations": state["iterations"] + 1}

    def tools_node(state: PlanState):
        last: AIMessage = state["messages"][-1]
        msgs, hits = [], []
        for call in last.tool_calls:
            t = by_name.get(call["name"])
            if t is None:
                msgs.append(ToolMessage(f"Unknown tool {call['name']}", tool_call_id=call["id"]))
                continue
            try:
                result = t.invoke(call["args"])
            except Exception as e:  # tool errors go back to the model, not to the user
                result = json.dumps({"error": str(e)})
            if call["name"] == "search_knowledge":
                data = json.loads(result)
                hits += [Hit(**h) for h in data.pop("_hits")]
                result = json.dumps(data, ensure_ascii=False)
            msgs.append(ToolMessage(result, tool_call_id=call["id"]))
        return {"messages": msgs, "retrieved": hits}

    def route(state: PlanState):
        last = state["messages"][-1]
        if (
            isinstance(last, AIMessage)
            and last.tool_calls
            and state["iterations"] < s.max_agent_iterations
        ):
            return "tools"
        return "finalize"

    def finalize(state: PlanState):
        version, text = client.prompt("planner_finalize")
        msgs = list(state["messages"])
        # A trailing AI message with unanswered tool calls is not valid input; drop it.
        if isinstance(msgs[-1], AIMessage) and msgs[-1].tool_calls:
            msgs = msgs[:-1]
        draft = llm_final.invoke(
            msgs + [HumanMessage(text)], config=cfg | {"metadata": {"prompt_version": version}}
        )
        return {"draft": draft}

    g = StateGraph(PlanState)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_node("finalize", finalize)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "finalize": "finalize"})
    g.add_edge("tools", "agent")
    g.add_edge("finalize", END)
    return g.compile()


# ---------- fallback ----------


def rule_based_draft(p: BuildingProfile) -> PlanDraft:
    year = p.year_built or 1970
    picks: list[tuple[str, str]] = []
    if year < 1995:
        picks.append(
            ("facade_insulation", "Walls from before 1995 usually have little or no insulation.")
        )
        picks.append(
            ("top_floor_ceiling_insulation", "Low cost and quick payback in older buildings.")
        )
    if year < 1985:
        picks.append(("windows", "Windows of this age are often double glazed with poor frames."))
        picks.append(
            ("basement_ceiling_insulation", "Cheap measure that reduces heat loss to the cellar.")
        )
    if p.heating_type in ("gas", "oil", "unknown"):
        picks.append(("heat_pump", "Replaces fossil heating; sized after envelope measures."))
    if p.building_type == "multi_family":
        picks.append(("pv", "Roof area of a multi-family building suits solar PV."))
    if not picks:
        picks.append(("pv", "The building is already in good condition; PV adds renewable supply."))
    return PlanDraft(
        summary="Rule-based plan: AI planning was unavailable, so measures were chosen by building age "
        "and heating type. Please review before sharing.",
        measures=[
            DraftMeasure(measure_id=m, priority=i + 1, rationale=r)
            for i, (m, r) in enumerate(picks)
        ],
        assumptions=["Chosen by fixed rules, not by the AI planner."],
        confidence=0.4,
    )


# ---------- assemble ----------


def assemble(
    draft: PlanDraft, req: PlanRequest, hits: list[Hit], run: Run, planner: str
) -> RetrofitPlan:
    issues: list[Issue] = []
    seen, measures_d = set(), []
    for m in sorted(draft.measures, key=lambda m: m.priority):
        if m.measure_id not in seen:
            seen.add(m.measure_id)
            measures_d.append(m)

    with run.span("plan_guardrails", kind="guardrail") as sp:
        by_id = {h.chunk_id: h for h in hits}
        bad = sorted({c for m in measures_d for c in m.citation_ids if c not in by_id})
        if bad:
            issues.append(
                Issue(
                    code="invalid_citation",
                    severity="warning",
                    message=f"Removed citations that the agent never retrieved: {bad}",
                )
            )
        if planner == "agent" and not any(c in by_id for m in measures_d for c in m.citation_ids):
            issues.append(
                Issue(
                    code="no_citations",
                    severity="warning",
                    message="The plan is not backed by any retrieved source.",
                )
            )
        if draft.confidence < 0.6:
            issues.append(
                Issue(
                    code="low_confidence",
                    severity="warning",
                    message=f"Planner confidence is {draft.confidence:.2f}.",
                )
            )
        p = req.profile
        if not p.living_area_m2 or not p.final_energy_kwh_m2a:
            issues.append(
                Issue(
                    code="missing_inputs",
                    severity="error",
                    message="Area and final energy are needed to calculate costs and savings.",
                )
            )
        sp.meta["issue_codes"] = [i.code for i in issues]

    res = outcome([m.measure_id for m in measures_d], req)
    ests = {e.measure_id: e for e in res["estimates"]}
    planned = [
        PlannedMeasure(
            measure_id=m.measure_id,
            label=ests[m.measure_id].label,
            category=ests[m.measure_id].category,
            priority=m.priority,
            rationale=m.rationale,
            cost_eur_low=round(ests[m.measure_id].cost_low, -2),
            cost_eur_high=round(ests[m.measure_id].cost_high, -2),
            cost_eur=ests[m.measure_id].cost_mid,
            subsidy_eur=res["subsidies"][m.measure_id]["subsidy_eur"],
            subsidy_program=res["subsidies"][m.measure_id]["program"],
            saving_pct=ests[m.measure_id].saving_pct,
            citation_ids=[c for c in m.citation_ids if c in by_id],
        )
        for m in measures_d
    ]
    cited = {c for m in planned for c in m.citation_ids}
    modernisation = sum(pm.cost_eur - pm.subsidy_eur for pm in planned)
    needs_review = (
        planner != "agent"
        or any(i.severity == "error" for i in issues)
        or any(i.code in ("low_confidence", "no_citations") for i in issues)
    )
    run.needs_review = needs_review
    return RetrofitPlan(
        run_id=run.id,
        summary=draft.summary,
        measures=planned,
        total_cost_eur=res["total_cost_eur"],
        total_subsidy_eur=res["total_subsidy_eur"],
        net_cost_eur=res["net_cost_eur"],
        energy_before_kwh_m2a=res["energy_before_kwh_m2a"],
        energy_after_kwh_m2a=res["energy_after_kwh_m2a"],
        energy_class_before=res["energy_class_before"],
        energy_class_after=res["energy_class_after"],
        co2_before_t=res["co2_before_t"],
        co2_after_t=res["co2_after_t"],
        max_rent_increase_eur_m2_month=None
        if req.owner_occupied
        else calc.max_rent_increase(modernisation, float(req.profile.living_area_m2 or 0)),
        assumptions=draft.assumptions
        + [
            "Costs are indicative market ranges; a site visit sets the real price.",
            "Funding rates follow the BEG rules in force since 21 July 2026 (simplified).",
        ],
        citations=[to_citation(by_id[c]) for c in sorted(cited)],
        issues=issues,
        needs_review=needs_review,
        planner=planner,  # type: ignore[arg-type]
        steps=run.summary_steps(),
    )


def plan(req: PlanRequest, run: Run, llm_tools=None, llm_final=None) -> RetrofitPlan:
    version, system = client.prompt("planner")
    try:
        graph = build_graph(req, run, llm_tools, llm_final)
        with run.span("agent_graph", kind="step", prompt=version):
            state = graph.invoke(
                {
                    "messages": [SystemMessage(system), HumanMessage(profile_text(req))],
                    "retrieved": [],
                    "iterations": 0,
                    "draft": None,
                },
                config={"recursion_limit": 4 * get_settings().max_agent_iterations + 4},
            )
        return assemble(state["draft"], req, state["retrieved"], run, "agent")
    except Exception as exc:
        run.fallback_used = True
        run.event("planner_fallback", kind="fallback", error=f"{type(exc).__name__}: {exc}"[:200])
        hits = knowledge().search("funding rates envelope heating multi-family", k=3)
        draft = rule_based_draft(req.profile)
        return assemble(draft, req, hits, run, "rule_based_fallback")
