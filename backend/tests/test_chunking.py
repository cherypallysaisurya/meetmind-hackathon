from app.prep.chunking import Passage, chunk, split_long


def test_passages_pack_into_chunks_and_a_new_location_starts_a_new_chunk():
    passages = [Passage("page 1", "First paragraph."), Passage("page 1", "Second paragraph."), Passage("page 2", "On the next page.")]
    chunks = chunk(passages, "notes.pdf", target_chars=1000, overlap_chars=50)
    assert [(c.index, c.location, c.text) for c in chunks] == [
        (0, "page 1", "First paragraph. Second paragraph."),
        (1, "page 2", "On the next page."),
    ]
    assert all(c.document_name == "notes.pdf" for c in chunks)


def test_a_full_chunk_carries_its_last_words_into_the_next():
    passages = [Passage("section: a", "alpha beta gamma delta"), Passage("section: a", "epsilon zeta eta theta")]
    chunks = chunk(passages, "x.md", target_chars=30, overlap_chars=11)
    assert chunks[0].text == "alpha beta gamma delta"
    assert chunks[1].text.startswith("gamma delta epsilon"), chunks[1].text


def test_a_long_paragraph_is_split_at_sentence_ends():
    pieces = split_long("One sentence here. Another one follows. And a third.", target_chars=40)
    assert pieces == ["One sentence here. Another one follows.", "And a third."]


def test_whitespace_is_normalized_and_empty_passages_skipped():
    chunks = chunk([Passage("p", "  a\n\n b  "), Passage("p", "   ")], "x.txt", 100, 10)
    assert [c.text for c in chunks] == ["a b"]
