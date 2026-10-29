"""Evaluation harness.

    python -m evals.run_evals                 # offline suites only (retrieval, guardrails)
    python -m evals.run_evals --llm           # adds extraction, answers and planning (needs API key)
    python -m evals.run_evals --llm --gate    # exit 1 if any metric is below evals/thresholds.json

Suites
- retrieval:  hit@5 and MRR for hybrid vs dense vs sparse search (no LLM, runs in CI)
- guardrails: regex baseline on text PDFs + expected issues (no LLM, runs in CI)
- extraction: field accuracy of the AI extractor on the labelled samples
- answers:    must-mention rate, correct refusals, and LLM-as-judge faithfulness (1-5)
- planning:   valid citation rate and plans without errors on the sample buildings

The report goes to evals/reports/latest.json and is shown on the Evals page.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import REPO_ROOT, get_settings
from app.extraction import extractor
from app.guardrails import checks
from app.llm import client
from app.observability.tracer import start_run
from app.rag.answer import ask, format_sources
from app.rag.store import knowledge

HERE = Path(__file__).parent


def load(name: str) -> list[dict]:
    return [
        json.loads(ln) for ln in (HERE / "datasets" / name).read_text().splitlines() if ln.strip()
    ]


def field_match(field: str, got, want) -> bool:
    if want is None:
        return got is None
    if isinstance(want, float) or field in ("living_area_m2", "final_energy_kwh_m2a"):
        return got is not None and abs(float(got) - float(want)) <= 0.01 * abs(float(want)) + 0.05
    return got == want


# ---------- suites ----------


def eval_retrieval() -> dict:
    kb = knowledge()
    rows = [r for r in load("rag.jsonl") if r["expected_docs"]]
    out = {}
    for mode in ("hybrid", "dense", "sparse"):
        hits, rr = 0, 0.0
        for r in rows:
            docs = [h.chunk_id.split("#")[0] for h in kb.search(r["question"], k=5, mode=mode)]
            rank = next((i + 1 for i, d in enumerate(docs) if d in r["expected_docs"]), None)
            hits += rank is not None
            rr += 1 / rank if rank else 0
        out[mode] = {"hit_at_5": round(hits / len(rows), 3), "mrr": round(rr / len(rows), 3)}
    return {"n": len(rows), "embeddings": kb.embedding_backend, **out["hybrid"], "by_mode": out}


def eval_guardrails() -> dict:
    rows = [r for r in load("extraction.jsonl") if r["kind"] == "text"]
    correct = total = issue_hits = issue_total = 0
    for r in rows:
        text, _ = extractor.pdf_text((REPO_ROOT / r["file"]).read_bytes(), 10)
        p = extractor.regex_extract(text)
        for f, want in r["expected"].items():
            total += 1
            correct += field_match(f, getattr(p, f), want)
        codes = {i.code for i in checks.injection_issues(text) + checks.sanity_issues(p)}
        for exp in r["expect_issues"]:
            issue_total += 1
            issue_hits += exp in codes
    return {
        "n": len(rows),
        "regex_field_accuracy": round(correct / total, 3),
        "expected_issue_recall": round(issue_hits / issue_total, 3) if issue_total else 1.0,
    }


def eval_extraction() -> dict:
    correct = total = issue_hits = issue_total = 0
    per_sample, cost = [], 0.0
    for r in load("extraction.jsonl"):
        extractor._cache.clear()
        with start_run("eval_extract", sample=r["id"]) as run:
            res = extractor.extract((REPO_ROOT / r["file"]).read_bytes(), r["file"], run)
        cost += run.cost_usd
        wrong = []
        for f, want in r["expected"].items():
            total += 1
            ok = field_match(f, getattr(res.profile, f), want)
            correct += ok
            if not ok:
                wrong.append({"field": f, "want": want, "got": getattr(res.profile, f)})
        codes = {i.code for i in res.issues}
        for exp in r["expect_issues"]:
            issue_total += 1
            issue_hits += exp in codes
        per_sample.append(
            {"id": r["id"], "mode": res.mode, "wrong": wrong, "needs_review": res.needs_review}
        )
    return {
        "n": len(per_sample),
        "field_accuracy": round(correct / total, 3),
        "expected_issue_recall": round(issue_hits / issue_total, 3) if issue_total else 1.0,
        "cost_usd": round(cost, 4),
        "samples": per_sample,
    }


class Judgement(BaseModel):
    score: int = Field(ge=1, le=5)
    reasoning: str


def eval_answers() -> dict:
    version, judge_prompt = client.prompt("judge")
    judge = client.structured(Judgement, name="judge")
    kb = knowledge()
    scores, mentions, refusals_ok, n_ref, cost, rows_out = [], 0, 0, 0, 0.0, []
    rows = load("rag.jsonl")
    for r in rows:
        with start_run("eval_answer", question=r["id"]) as run:
            res = ask(r["question"], run)
        cost += run.cost_usd
        if r.get("unanswerable"):
            n_ref += 1
            refusals_ok += not res.answerable
            rows_out.append({"id": r["id"], "refused": not res.answerable})
            continue
        mentioned = all(m.lower() in res.answer.lower() for m in r["must_mention"])
        mentions += mentioned
        sources = format_sources(kb.search(r["question"]))
        j = judge.invoke(
            f"{judge_prompt}\n\n<sources>\n{sources}\n</sources>\n\nQuestion: {r['question']}\n"
            f"Answer: {res.answer}"
        )
        scores.append(j.score)
        rows_out.append(
            {"id": r["id"], "faithfulness": j.score, "mentioned": mentioned, "why": j.reasoning}
        )
    answerable = len(rows) - n_ref
    return {
        "n": len(rows),
        "faithfulness_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "mention_rate": round(mentions / answerable, 3),
        "refusal_correct": round(refusals_ok / n_ref, 3) if n_ref else 1.0,
        "judge_prompt": version,
        "cost_usd": round(cost, 4),
        "rows": rows_out,
    }


def eval_planning() -> dict:
    from app.agent.planner import plan
    from app.schemas import BuildingProfile, PlanRequest

    rows = [r for r in load("extraction.jsonl") if r["kind"] == "text"][:4]
    valid = cited = ok = 0
    cost, out = 0.0, []
    for r in rows:
        prof = BuildingProfile(**r["expected"])
        with start_run("eval_plan", sample=r["id"]) as run:
            res = plan(PlanRequest(profile=prof), run)
        cost += run.cost_usd
        ids = [c for m in res.measures for c in m.citation_ids]
        cited += len(ids) + sum(i.code == "invalid_citation" for i in res.issues)
        valid += len(ids)
        ok += not any(i.severity == "error" for i in res.issues) and res.planner == "agent"
        out.append(
            {
                "id": r["id"],
                "planner": res.planner,
                "measures": [m.measure_id for m in res.measures],
                "issues": [i.code for i in res.issues],
            }
        )
    return {
        "n": len(rows),
        "valid_citation_rate": round(valid / cited, 3) if cited else 0.0,
        "plans_without_errors": round(ok / len(rows), 3),
        "cost_usd": round(cost, 4),
        "rows": out,
    }


# ---------- runner ----------


def gate(report: dict, thresholds: dict) -> list[str]:
    failures = []
    for suite, metrics in thresholds.items():
        if suite not in report["suites"]:
            continue
        for metric, minimum in metrics.items():
            got = report["suites"][suite].get(metric)
            if got is not None and got < minimum:
                failures.append(f"{suite}.{metric} = {got} < {minimum}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="run suites that call the model")
    ap.add_argument("--gate", action="store_true", help="exit 1 if below thresholds")
    args = ap.parse_args()

    s = get_settings()
    suites = {"retrieval": eval_retrieval, "guardrails": eval_guardrails}
    if args.llm:
        if not s.llm_enabled:
            print("ANTHROPIC_API_KEY not set; skipping LLM suites")
        else:
            suites |= {
                "extraction": eval_extraction,
                "answers": eval_answers,
                "planning": eval_planning,
            }

    t0 = time.time()
    report = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": s.primary_model,
        "suites": {},
    }
    for name, fn in suites.items():
        print(f"running {name} ...", flush=True)
        report["suites"][name] = fn()
    report["duration_s"] = round(time.time() - t0, 1)
    thresholds = json.loads((HERE / "thresholds.json").read_text())
    report["failures"] = gate(report, thresholds)
    report["thresholds"] = thresholds

    s.eval_report_dir.mkdir(parents=True, exist_ok=True)
    (s.eval_report_dir / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    for name, res in report["suites"].items():
        summary = {k: v for k, v in res.items() if not isinstance(v, (list, dict))}
        print(f"{name:11s} {summary}")
    if report["failures"]:
        print("BELOW THRESHOLD:\n  " + "\n  ".join(report["failures"]))
    return 1 if (args.gate and report["failures"]) else 0


if __name__ == "__main__":
    sys.exit(main())
