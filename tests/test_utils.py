from pst_agent.utils import chunk_text, to_fts_query


def test_chunk_text_creates_multiple_chunks() -> None:
    text = "a" * 4000
    chunks = chunk_text(text, size=1000, overlap=100)
    assert len(chunks) >= 4
    assert chunks[0]["start_char"] == 0


def test_to_fts_query_adds_prefix_match() -> None:
    assert to_fts_query("Contract update 2026") == "contract* update* 2026*"
