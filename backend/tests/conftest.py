import os
import tempfile

# Offline, deterministic test environment: no API key, hash embeddings, in-memory Qdrant.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["LANGSMITH_TRACING"] = "false"  # never send test runs to LangSmith
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["QDRANT_URL"] = "http://127.0.0.1:1"
os.environ["TELEMETRY_DB"] = os.path.join(tempfile.mkdtemp(), "telemetry.db")
os.environ["EVAL_REPORT_DIR"] = tempfile.mkdtemp()
