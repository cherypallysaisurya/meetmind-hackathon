"""Documents in, chunks and vectors out. Parse, chunk, embed, store the vectors in the user's collection
and the record in the store. Removing a document removes its vectors too."""

import time
from uuid import uuid4

from ..ports import Document, DocumentParser, Embeddings, Store, VectorStore


def collection_for(user_id: str) -> str:
    return f"docs:{user_id}"


class Documents:
    def __init__(self, parser: DocumentParser, embeddings: Embeddings, vectors: VectorStore, store: Store):
        self.parser = parser
        self.embeddings = embeddings
        self.vectors = vectors
        self.store = store

    async def add(self, user_id: str, filename: str, data: bytes) -> Document:
        chunks = await self.parser.parse(filename, data)
        if not chunks:
            raise ValueError(f"{filename} has no readable text")
        doc_id = uuid4().hex
        # The heading of a section lives in the chunk's location, not its text. Embedding the document name and
        # location with the text lets a question like "the plan for next week" find the section with that heading.
        vectors = await self.embeddings.embed([f"{c.document_name}, {c.location}: {c.text}" for c in chunks])
        await self.vectors.add(
            collection_for(user_id),
            ids=[f"{doc_id}:{c.index}" for c in chunks],
            vectors=vectors,
            metadata=[{"doc_id": doc_id, "document": filename, "location": c.location, "index": c.index, "text": c.text} for c in chunks],
        )
        document = Document(user_id, doc_id, filename, filename.rsplit(".", 1)[-1].lower(), int(time.time()), len(chunks), "ready")
        await self.store.save_document(document)
        return document

    async def list(self, user_id: str) -> list[Document]:
        return sorted(await self.store.list_documents(user_id), key=lambda d: d.added_at)

    async def remove(self, user_id: str, doc_id: str) -> None:
        for document in await self.store.list_documents(user_id):
            if document.doc_id == doc_id:
                await self.vectors.delete(collection_for(user_id), [f"{doc_id}:{i}" for i in range(document.chunk_count)])
                await self.store.delete_document(user_id, doc_id)
