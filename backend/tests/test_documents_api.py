import pytest
from fastapi.testclient import TestClient

from app import main
from app.adapters.factory import make_document_parser
from app.main import app
from app.prep.documents import Documents, collection_for
from tests.contract.document_parser_contract import FIXTURES
from tests.fakes import HashEmbeddings, InMemoryStore, InMemoryVectorStore


@pytest.fixture
def fake_documents(monkeypatch):
    docs = Documents(make_document_parser(), HashEmbeddings(), InMemoryVectorStore(), InMemoryStore())
    monkeypatch.setattr(main, "documents", docs)
    return docs


def test_upload_list_delete_round_trip(fake_documents):
    client = TestClient(app)
    assert client.get("/api/documents").json() == {"documents": []}

    uploaded = client.post("/api/documents", files={"file": ("notes.md", b"# Results\n\nThe rebuild takes twelve minutes.\n", "text/markdown")})
    assert uploaded.status_code == 200, uploaded.text
    record = uploaded.json()
    assert record["name"] == "notes.md" and record["type"] == "md" and record["chunkCount"] == 1 and record["status"] == "ready"

    pdf = client.post("/api/documents", files={"file": ("notes.pdf", (FIXTURES / "notes.pdf").read_bytes(), "application/pdf")})
    assert pdf.status_code == 200 and pdf.json()["chunkCount"] >= 1

    listed = client.get("/api/documents").json()["documents"]
    assert [d["name"] for d in listed] == ["notes.md", "notes.pdf"]
    assert len(fake_documents.vectors.rows[collection_for("local")]) == record["chunkCount"] + pdf.json()["chunkCount"]

    assert client.delete(f"/api/documents/{record['docId']}").json() == {"deleted": record["docId"]}
    assert [d["name"] for d in client.get("/api/documents").json()["documents"]] == ["notes.pdf"]
    assert len(fake_documents.vectors.rows[collection_for("local")]) == pdf.json()["chunkCount"], "the deleted document's vectors are gone"


def test_unsupported_and_empty_files_are_refused(fake_documents):
    client = TestClient(app)
    assert client.post("/api/documents", files={"file": ("photo.png", b"\x89PNG", "image/png")}).status_code == 415
    assert client.post("/api/documents", files={"file": ("empty.txt", b"   ", "text/plain")}).status_code == 422


async def test_the_embedded_text_carries_document_name_and_location():
    class RecordingEmbeddings(HashEmbeddings):
        async def embed(self, texts):
            self.seen = texts
            return await super().embed(texts)

    embeddings = RecordingEmbeddings()
    docs = Documents(make_document_parser(), embeddings, InMemoryVectorStore(), InMemoryStore())
    await docs.add("local", "plan.md", b"# Plan for next week\n\n1. Finish PDF support.\n")
    assert embeddings.seen == ["plan.md, section: Plan for next week: 1. Finish PDF support."]
