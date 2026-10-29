"""Lightweight tracing for every AI run.

Each API request that touches AI opens a *run*. Inside a run we record *spans*:
LLM calls (model, tokens, cost, latency), tool calls, retrieval, guardrail checks and
fallbacks. Everything goes to SQLite so the Observability page and /api/metrics work
with no external service. If Langfuse keys are set, LangChain traces are also sent there.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.config import get_settings
from app.llm.pricing import cost_usd

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, kind TEXT, started_at REAL, duration_ms REAL, status TEXT,
  cost_usd REAL, input_tokens INTEGER, output_tokens INTEGER, llm_calls INTEGER,
  fallback_used INTEGER, needs_review INTEGER, error TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS spans (
  id TEXT PRIMARY KEY, run_id TEXT, name TEXT, kind TEXT, started_at REAL, duration_ms REAL,
  status TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
  error TEXT, meta TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, field TEXT, predicted TEXT,
  corrected TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id);
"""


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Span:
    name: str
    kind: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    status: str = "ok"
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class Run:
    kind: str
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    spans: list[Span] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None
    needs_review: bool = False
    fallback_used: bool = False
    budget_usd: float = 0.5
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    @property
    def cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.spans), 6)

    def check_budget(self) -> None:
        if self.cost_usd > self.budget_usd:
            raise BudgetExceeded(f"Run cost {self.cost_usd:.4f} USD exceeds {self.budget_usd} USD")

    @contextmanager
    def span(self, name: str, kind: str, **meta: Any):
        s = Span(name=name, kind=kind, meta=meta)
        t0 = time.perf_counter()
        try:
            yield s
        except Exception as exc:
            s.status, s.error = "error", f"{type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            s.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            self.add(s)

    def event(self, name: str, kind: str = "event", **meta: Any) -> None:
        self.add(Span(name=name, kind=kind, meta=meta))

    def summary_steps(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "model": s.model,
                "tokens": s.input_tokens + s.output_tokens,
                "cost_usd": round(s.cost_usd, 5),
                "meta": s.meta,
            }
            for s in sorted(self.spans, key=lambda s: s.started_at)
        ]


class TelemetryCallback(BaseCallbackHandler):
    """LangChain callback that turns LLM and tool events into spans on a Run."""

    raise_error = True  # lets BudgetExceeded stop the chain

    def __init__(self, run: Run):
        self.run = run
        self._open: dict[str, tuple[Span, float]] = {}

    # LLM
    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name")
        s = Span(name=kwargs.get("name") or "llm", kind="llm", model=model)
        s.meta["prompt_version"] = (kwargs.get("metadata") or {}).get("prompt_version")
        self._open[str(run_id)] = (s, time.perf_counter())

    def on_llm_end(self, response, *, run_id, **kwargs):
        s, t0 = self._open.pop(str(run_id), (Span(name="llm", kind="llm"), time.perf_counter()))
        s.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            msg = response.generations[0][0].message
            usage = getattr(msg, "usage_metadata", None) or {}
            s.input_tokens = int(usage.get("input_tokens", 0))
            s.output_tokens = int(usage.get("output_tokens", 0))
            s.model = (msg.response_metadata or {}).get("model") or s.model
            s.meta["tool_calls"] = [tc["name"] for tc in getattr(msg, "tool_calls", []) or []]
        except (IndexError, AttributeError):
            pass
        s.cost_usd = cost_usd(s.model, s.input_tokens, s.output_tokens)
        settings = get_settings()
        if s.model and settings.fallback_model in s.model:
            self.run.fallback_used = True
            s.meta["fallback"] = True
        self.run.add(s)
        self.run.check_budget()

    def on_llm_error(self, error, *, run_id, **kwargs):
        s, t0 = self._open.pop(str(run_id), (Span(name="llm", kind="llm"), time.perf_counter()))
        s.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        s.status, s.error = "error", f"{type(error).__name__}: {error}"[:500]
        self.run.add(s)


class TelemetryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.path, check_same_thread=False)

    def save(self, run: Run) -> None:
        duration = (time.time() - run.started_at) * 1000
        llm = [s for s in run.spans if s.kind == "llm"]
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.kind,
                    run.started_at,
                    round(duration, 1),
                    run.status,
                    run.cost_usd,
                    sum(s.input_tokens for s in llm),
                    sum(s.output_tokens for s in llm),
                    len(llm),
                    int(run.fallback_used),
                    int(run.needs_review),
                    run.error,
                    json.dumps(run.meta, default=str),
                ),
            )
            c.executemany(
                "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        s.id,
                        run.id,
                        s.name,
                        s.kind,
                        s.started_at,
                        s.duration_ms,
                        s.status,
                        s.model,
                        s.input_tokens,
                        s.output_tokens,
                        s.cost_usd,
                        s.error,
                        json.dumps(s.meta, default=str),
                    )
                    for s in run.spans
                ],
            )

    def add_feedback(self, run_id: str, field_name: str, predicted: str | None, corrected: str):
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO feedback (run_id, field, predicted, corrected, created_at) "
                "VALUES (?,?,?,?,?)",
                (run_id, field_name, predicted, corrected, time.time()),
            )

    def recent_runs(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) | {"meta": json.loads(r["meta"] or "{}")} for r in rows]

    def run_spans(self, run_id: str) -> list[dict]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM spans WHERE run_id=? ORDER BY started_at", (run_id,)
            ).fetchall()
        return [dict(r) | {"meta": json.loads(r["meta"] or "{}")} for r in rows]

    def metrics(self) -> dict:
        with self._conn() as c:
            runs = c.execute(
                "SELECT kind, duration_ms, status, cost_usd, fallback_used, needs_review FROM runs"
            ).fetchall()
            llm = c.execute(
                "SELECT model, duration_ms, status, input_tokens, output_tokens, cost_usd "
                "FROM spans WHERE kind='llm'"
            ).fetchall()
            fb = c.execute("SELECT field, COUNT(*) FROM feedback GROUP BY field").fetchall()

        def pct(values: list[float], q: float) -> float | None:
            if not values:
                return None
            v = sorted(values)
            return round(v[min(len(v) - 1, int(q * len(v)))], 1)

        by_kind: dict[str, dict] = {}
        for kind in sorted({r[0] for r in runs}):
            rs = [r for r in runs if r[0] == kind]
            durations = [r[1] for r in rs]
            by_kind[kind] = {
                "runs": len(rs),
                "p50_ms": pct(durations, 0.5),
                "p95_ms": pct(durations, 0.95),
                "error_rate": round(sum(r[2] != "ok" for r in rs) / len(rs), 3),
                "avg_cost_usd": round(sum(r[3] for r in rs) / len(rs), 5),
                "fallback_rate": round(sum(r[4] for r in rs) / len(rs), 3),
                "review_rate": round(sum(r[5] for r in rs) / len(rs), 3),
            }
        by_model: dict[str, dict] = {}
        for model in sorted({r[0] or "unknown" for r in llm}):
            ls = [r for r in llm if (r[0] or "unknown") == model]
            by_model[model] = {
                "calls": len(ls),
                "p50_ms": pct([r[1] for r in ls], 0.5),
                "p95_ms": pct([r[1] for r in ls], 0.95),
                "error_rate": round(sum(r[2] != "ok" for r in ls) / len(ls), 3),
                "input_tokens": sum(r[3] or 0 for r in ls),
                "output_tokens": sum(r[4] or 0 for r in ls),
                "cost_usd": round(sum(r[5] or 0 for r in ls), 4),
            }
        return {
            "total_runs": len(runs),
            "total_cost_usd": round(sum(r[3] for r in runs), 4),
            "by_kind": by_kind,
            "by_model": by_model,
            "feedback_by_field": dict(fb),
        }


_store: TelemetryStore | None = None


def store() -> TelemetryStore:
    global _store
    if _store is None:
        _store = TelemetryStore(get_settings().telemetry_db)
    return _store


def callbacks_for(run: Run) -> list:
    """Callbacks to pass in a LangChain config: our telemetry, plus Langfuse if configured."""
    cbs: list = [TelemetryCallback(run)]
    s = get_settings()
    if s.langfuse_public_key and s.langfuse_secret_key:
        try:  # optional dependency
            from langfuse.langchain import CallbackHandler  # type: ignore

            cbs.append(CallbackHandler())
        except Exception:  # noqa: BLE001
            run.event("langfuse_unavailable", kind="warning")
    return cbs


@contextmanager
def start_run(kind: str, **meta: Any):
    run = Run(kind=kind, meta=meta, budget_usd=get_settings().max_run_cost_usd)
    try:
        yield run
    except Exception as exc:
        run.status, run.error = "error", f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        store().save(run)
