"""HTTP API for Retrofit Copilot."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.agent import planner
from app.config import get_settings
from app.extraction import extractor
from app.guardrails.checks import InputRejected
from app.observability.tracer import start_run, store
from app.rag import answer
from app.rag.store import knowledge
from app.schemas import (
    AskRequest,
    AskResponse,
    ExtractionResult,
    Feedback,
    PlanRequest,
    RetrofitPlan,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    knowledge()  # index the knowledge base at startup
    yield


app = FastAPI(title="Retrofit Copilot", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    kb = knowledge()
    return {
        "status": "ok",
        "llm_enabled": s.llm_enabled,
        "primary_model": s.primary_model,
        "fallback_model": s.fallback_model,
        "qdrant_mode": kb.mode,
        "embeddings": kb.embedding_backend,
        "kb_chunks": len(kb.chunks),
        "kb_version": kb.kb_version,
    }


@app.post("/api/extract", response_model=ExtractionResult)
def extract(file: UploadFile = File(...)) -> ExtractionResult:
    data = file.file.read()
    with start_run("extract", filename=file.filename) as run:
        try:
            return extractor.extract(data, file.filename or "upload", run)
        except InputRejected as e:
            run.status, run.error = "rejected", str(e)
            raise HTTPException(status_code=422, detail=str(e)) from e


SAMPLE_TYPES = {".pdf", ".jpg", ".jpeg", ".png"}


@app.get("/api/samples")
def samples() -> list[dict]:
    folder = get_settings().data_dir / "samples"
    return [
        {
            "name": p.name,
            "kind": "photo" if p.suffix != ".pdf" else ("scan" if "scan" in p.stem else "pdf"),
        }
        for p in sorted(folder.iterdir())
        if p.suffix.lower() in SAMPLE_TYPES
    ]


@app.post("/api/extract/sample/{name}", response_model=ExtractionResult)
def extract_sample(name: str) -> ExtractionResult:
    folder = get_settings().data_dir / "samples"
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown sample")
    with start_run("extract", filename=name, sample=True) as run:
        return extractor.extract(path.read_bytes(), name, run)


@app.post("/api/plan", response_model=RetrofitPlan)
def plan(req: PlanRequest) -> RetrofitPlan:
    with start_run("plan", owner_occupied=req.owner_occupied, has_isfp=req.has_isfp) as run:
        result = planner.plan(req, run)
        result.steps = run.summary_steps()
        return result


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    with start_run("ask", question=req.question) as run:
        return answer.ask(req.question, run)


@app.post("/api/feedback")
def feedback(fb: Feedback) -> dict:
    """Human corrections. They show up in metrics and can be promoted into the eval set."""
    store().add_feedback(fb.run_id, fb.field, fb.predicted, fb.corrected)
    return {"ok": True}


@app.get("/api/runs")
def runs(limit: int = 50) -> list[dict]:
    return store().recent_runs(limit)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> list[dict]:
    return store().run_spans(run_id)


@app.get("/api/metrics")
def metrics() -> dict:
    return store().metrics()


@app.get("/api/evals/latest")
def latest_eval() -> dict:
    path = get_settings().eval_report_dir / "latest.json"
    if not path.exists():
        return {"available": False}
    return {"available": True} | json.loads(path.read_text())
