"""Contract every DocumentParser adapter must pass.

The fixtures notes.txt, notes.pdf and notes.docx hold the same short document. Every parsed version
must contain the phrase below somewhere, and every chunk must know where it came from.
"""

from pathlib import Path

import pytest

from app.ports import Chunk, DocumentParser

FIXTURES = Path(__file__).parent / "fixtures"
PHRASE = "twelve minutes"

MARKDOWN = """# Results

The retrieval index rebuild now takes twelve minutes instead of forty.

## Next steps

Decide on the evaluation set before Friday.
"""


def check_chunks(chunks: list[Chunk], filename: str):
    assert chunks, f"{filename} produced no chunks"
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.document_name == filename
        assert chunk.location.strip()
        assert chunk.text.strip()
    assert PHRASE in " ".join(c.text for c in chunks).lower()


class DocumentParserContract:
    def make_adapter(self) -> DocumentParser:
        raise NotImplementedError("the adapter test must build its adapter here")

    def test_supports_the_required_types(self):
        supported = self.make_adapter().supported_types()
        assert {"pdf", "md", "txt"} <= supported

    async def test_markdown(self):
        chunks = await self.make_adapter().parse("notes.md", MARKDOWN.encode())
        check_chunks(chunks, "notes.md")

    @pytest.mark.parametrize("filename", ["notes.txt", "notes.pdf", "notes.docx"])
    async def test_fixture_files(self, filename):
        parser = self.make_adapter()
        extension = filename.rsplit(".", 1)[1]
        if extension not in parser.supported_types():
            pytest.skip(f"{extension} is not supported by this adapter")
        chunks = await parser.parse(filename, (FIXTURES / filename).read_bytes())
        check_chunks(chunks, filename)
