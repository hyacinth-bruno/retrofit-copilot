from app.config import REPO_ROOT
from app.extraction import extractor
from app.observability.tracer import start_run


def _run(name):
    extractor._cache.clear()
    data = (REPO_ROOT / "data" / "samples" / name).read_bytes()
    with start_run("test_extract") as run:
        return extractor.extract(data, name, run), run


def test_without_key_falls_back_to_regex_and_flags_review():
    res, run = _run("mfh_1968_gas.pdf")
    assert res.mode == "regex_fallback"
    assert res.profile.year_built == 1968 and res.profile.final_energy_kwh_m2a == 187.3
    assert res.needs_review and run.fallback_used
    assert any(i.code == "ai_fallback" for i in res.issues)


def test_scan_without_key_asks_for_manual_entry():
    res, _ = _run("mfh_1962_scan.pdf")
    assert res.mode == "none"
    assert any(i.code == "ai_unavailable" and i.severity == "error" for i in res.issues)


def test_injection_sample_is_flagged():
    res, _ = _run("mfh_1972_injection.pdf")
    assert any(i.code == "prompt_injection_suspected" for i in res.issues)
    assert res.profile.energy_class == "F"  # the injected "A+" was not obeyed
