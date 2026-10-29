.PHONY: setup api web qdrant test lint evals evals-llm samples

setup:            ## create venv and install everything
	python3 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements-dev.txt
	cd frontend && npm install

qdrant:           ## start Qdrant only
	docker compose up -d qdrant

api:              ## run the API with reload
	. .venv/bin/activate && cd backend && uvicorn app.main:app --reload --port 8000

web:              ## run the UI
	cd frontend && npm run dev

test:             ## unit and API tests (offline, no key needed)
	. .venv/bin/activate && cd backend && python -m pytest

lint:
	. .venv/bin/activate && cd backend && ruff check . && ruff format --check .
	cd frontend && npm run typecheck

evals:            ## offline eval suites
	. .venv/bin/activate && cd backend && python -m evals.run_evals --gate

evals-llm:        ## all eval suites, calls Claude (costs a few cents)
	. .venv/bin/activate && cd backend && python -m evals.run_evals --llm --gate

samples:          ## regenerate the fictional certificates
	. .venv/bin/activate && cd backend && python scripts/make_samples.py
