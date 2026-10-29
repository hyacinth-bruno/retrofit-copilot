from app.config import get_settings
from app.rag.store import chunk_markdown, knowledge


def test_chunks_have_stable_ids():
    chunks = chunk_markdown(get_settings().data_dir / "knowledge" / "beg-em-envelope.md")
    assert chunks[0].chunk_id == "beg-em-envelope#0"
    assert all(c.url and c.text for c in chunks)


def test_hybrid_search_finds_exact_terms():
    hits = knowledge().search("iSFP bonus after the reform", k=3)
    assert hits[0].chunk_id.startswith("beg-em-envelope")


def test_german_query_finds_heating_doc():
    hits = knowledge().search("Zuschuss Wärmepumpe KfW 458", k=3)
    assert any(h.chunk_id.startswith("beg-em-heating") for h in hits)
