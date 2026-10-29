"""Grounded question answering over the knowledge base."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.llm import client
from app.observability.tracer import Run, callbacks_for
from app.rag.store import Hit, knowledge
from app.schemas import AnswerDraft, AskResponse, Citation, Issue


def format_sources(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{h.chunk_id}] {h.title} — {h.section}\n{h.text}" for h in hits)


def to_citation(h: Hit) -> Citation:
    return Citation(
        chunk_id=h.chunk_id, title=f"{h.title} — {h.section}", url=h.url, snippet=h.text[:280]
    )


def ask(question: str, run: Run) -> AskResponse:
    s = get_settings()
    issues: list[Issue] = []
    with run.span("retrieve", kind="retrieval", query=question) as sp:
        hits = knowledge().search(question)
        sp.meta.update(chunk_ids=[h.chunk_id for h in hits], scores=[h.score for h in hits])

    if not hits or hits[0].score < s.retrieval_min_score:
        run.needs_review = True
        return AskResponse(
            run_id=run.id,
            answer="I could not find this in the knowledge base.",
            citations=[],
            answerable=False,
            mode="refused",
            issues=issues,
        )

    version, system = client.prompt("answer")
    try:
        llm = client.structured(AnswerDraft, name="answer")
        draft: AnswerDraft = llm.invoke(
            [
                SystemMessage(system),
                HumanMessage(
                    f"<sources>\n{format_sources(hits)}\n</sources>\n\nQuestion: {question}"
                ),
            ],
            config={"callbacks": callbacks_for(run), "metadata": {"prompt_version": version}},
        )
    except Exception as exc:  # no key, both models down, budget
        run.fallback_used = True
        run.event("answer_fallback", kind="fallback", error=str(exc)[:200])
        top = hits[:2]
        return AskResponse(
            run_id=run.id,
            answer="AI answers are unavailable right now. These are the most relevant passages:\n\n"
            + "\n\n".join(f"{h.text[:400]}" for h in top),
            citations=[to_citation(h) for h in top],
            answerable=True,
            mode="extractive_fallback",
            issues=issues,
        )

    with run.span("citation_guardrail", kind="guardrail") as sp:
        by_id = {h.chunk_id: h for h in hits}
        valid = [c for c in draft.citation_ids if c in by_id]
        invalid = [c for c in draft.citation_ids if c not in by_id]
        if invalid:
            issues.append(
                Issue(
                    code="invalid_citation",
                    severity="warning",
                    message=f"Removed citations that were not retrieved: {invalid}",
                )
            )
        if draft.answerable and not valid:
            issues.append(
                Issue(
                    code="uncited_answer",
                    severity="error",
                    message="The answer cited no retrieved source, so it was withheld.",
                )
            )
            draft = AnswerDraft(
                answer="I could not find a supported answer in the sources.",
                citation_ids=[],
                answerable=False,
            )
        sp.meta.update(valid=valid, invalid=invalid)

    run.needs_review = any(i.severity == "error" for i in issues)
    return AskResponse(
        run_id=run.id,
        answer=draft.answer,
        citations=[to_citation(by_id[c]) for c in valid],
        answerable=draft.answerable,
        mode="llm" if draft.answerable else "refused",
        issues=issues,
    )
