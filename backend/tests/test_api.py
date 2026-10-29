from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.main import app


def test_end_to_end_without_api_key():
    with TestClient(app) as c:
        h = c.get("/health").json()
        assert h["status"] == "ok" and h["llm_enabled"] is False and h["kb_chunks"] > 10

        pdf = (REPO_ROOT / "data" / "samples" / "mfh_1979_district.pdf").read_bytes()
        ex = c.post("/api/extract", files={"file": ("c.pdf", pdf, "application/pdf")}).json()
        assert ex["profile"]["dwelling_units"] == 12

        plan = c.post("/api/plan", json={"profile": ex["profile"]}).json()
        assert plan["planner"] == "rule_based_fallback" and plan["measures"]

        ans = c.post("/api/ask", json={"question": "How high is the iSFP bonus?"}).json()
        assert ans["mode"] == "extractive_fallback" and ans["citations"]

        bad = c.post(
            "/api/extract", files={"file": ("x.exe", b"MZ" * 200, "application/octet-stream")}
        )
        assert bad.status_code == 422

        m = c.get("/api/metrics").json()
        assert m["by_kind"]["plan"]["fallback_rate"] == 1.0
        assert c.get("/api/runs").json()
