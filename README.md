# Retrofit Copilot

An AI copilot for energy retrofits of multi-family buildings in Germany.

Upload an energy certificate (Energieausweis) as a PDF, scan or phone photo. Claude reads it into a typed building profile, guardrails check every value, and you correct anything that looks wrong. A LangGraph agent then researches the funding rules and proposes retrofit measures. Code calculates every cost, grant, CO₂ figure and rent effect, and the agent has to cite its sources.

I built this as a demo for an interview. All certificates, addresses and names in `data/samples` are fictional. The funding knowledge base is a simplified summary of the BEG rules in force since 21 July 2026, so it is not advice.

```
certificate ─► input guardrails ─► Claude (text or vision) ─► output guardrails ─► human review
                                                                                       │
                       knowledge base ◄── hybrid search ◄── LangGraph agent ◄──────────┘
                                                                │ tools: search, estimate, outcome
                                                                ▼
                                          code recalculates numbers + checks citations ─► plan
                         every step ─► traces (tokens, cost, latency, fallbacks) ─► dashboard
                         golden sets ─► eval harness ─► CI gate
```

## What it shows

| Job requirement | Where it is in the code |
|---|---|
| LLMs, AI APIs | `app/llm/client.py`: one shared client, Claude primary plus a fallback model |
| Multimodal | `app/extraction/extractor.py`: scans and photos go to Claude vision; text PDFs go as text |
| Embeddings, vector DB, RAG | `app/rag/store.py`: Qdrant, multilingual fastembed embeddings plus BM25 sparse vectors, fused with RRF |
| Agents and tool calling | `app/agent/planner.py`: a LangGraph state graph with three tools and a structured final answer |
| Hallucination reduction | Grounded quotes, citations checked against retrieved chunks, and numbers calculated in code |
| Guardrails and fallbacks | `app/guardrails/checks.py`: file sniffing, PII redaction, injection detection, sanity rules, confidence thresholds, rule-based fallbacks |
| Evaluation | `evals/run_evals.py`: retrieval hit@5 and MRR, field accuracy, LLM-as-judge faithfulness, CI threshold gate |
| Observability | `app/observability/tracer.py`: spans in SQLite, `/api/metrics`, Observability page, optional Langfuse |
| Latency and cost | Text-first extraction, a SHA-256 result cache, a per-run budget cap, p50/p95 and cost per feature |
| Reusable patterns | Shared LLM client, versioned prompts in `app/prompts/`, typed schemas, and one tracer for every feature |
| TypeScript product | `frontend/`: Next.js 14 and TypeScript, with Analyze, Ask, Observability and Evals pages |

## Run it

You need Python 3.11+, Node 20+ and, optionally, Docker for Qdrant.

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
make setup                    # venv + pip + npm
make qdrant                   # optional; without it an in-memory Qdrant is used
make api                      # http://localhost:8000  (docs at /docs)
make web                      # http://localhost:3000
```

Or everything in containers: `docker compose up --build`.

On the first start, fastembed downloads a multilingual embedding model of about 120 MB. Without an API key the app still works end to end on its fallbacks (rule-based extraction, rule-based planner, extractive answers), and the header shows that clearly.

### Check the model names and prices

`PRIMARY_MODEL` and `FALLBACK_MODEL` default to `claude-sonnet-5-5` and `claude-haiku-5-5`. The token prices in `app/llm/pricing.py` are assumptions. Check them against anthropic.com/pricing before you quote costs.

## Tests and evals

```bash
make test        # 21 tests, offline, no key needed
make lint
make evals       # offline suites: retrieval + guardrails, gated by evals/thresholds.json
make evals-llm   # adds extraction, grounded answers (LLM judge) and agent planning
```

CI (`.github/workflows/ci.yml`) runs lint, tests and the offline evals on every push. It runs the LLM evals only when the `ANTHROPIC_API_KEY` secret is set, and it fails the build when a metric drops below its threshold.

## Layout

```
backend/
  app/
    llm/            shared client (retries, timeout, fallback model, structured output) + pricing
    extraction/     certificate -> BuildingProfile (text / vision / regex fallback)
    guardrails/     input and output checks
    rag/            chunking, Qdrant hybrid search, grounded Q&A
    agent/          LangGraph planner, tools, rule-based fallback, plan assembly
    domain/         deterministic cost, grant, CO2 and rent maths
    observability/  runs, spans, metrics, Langfuse hook
    prompts/        versioned prompt files
  evals/            datasets, thresholds, runner
  tests/
  scripts/make_samples.py
data/
  knowledge/        markdown knowledge base (indexed at startup)
  reference/        cost, grant, CO2 and class tables
  samples/          fictional certificates (text PDFs, a scan, a phone photo)
frontend/           Next.js + TypeScript UI
docs/               architecture and decisions, demo script
```

See `docs/ARCHITECTURE.md` for the design decisions and trade-offs, and `docs/DEMO_SCRIPT.md` for a five-minute walkthrough.
