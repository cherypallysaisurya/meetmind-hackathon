# 0006: Local vector store: sqlite-vec

Status: accepted
Date: 2026-10-23

## Context

Decision 0003 added a VectorStore port for document chunks and prepared questions. Locally it needs an embedded store: no server, survives restarts, fits the sizes we have (tens of documents, a few thousand chunks, 768-number vectors from nomic-embed-text). The AWS option is chosen separately in Phase 4.

## Options considered

Measured on this Mac with 5,000 random unit vectors of 768 numbers, one query for the nearest ten:

| Store | Install footprint | Insert 5,000 | Query top 10 | Found the planted neighbor |
|---|---|---|---|---|
| sqlite-vec 0.1.9 | 168 KB, runs inside Python's SQLite | 0.26 s | 5 ms | yes |
| LanceDB 0.40.0 | 150 MB plus pyarrow 126 MB | 0.16 s | 13 ms | yes |

Chroma was not measured: it is heavier still and built around a client and server model we do not need for one user on one Mac.

## Decision

sqlite-vec. One file (`data/vectors.db`, git-ignored), SQL for everything, a cosine distance index, partition by collection, metadata stored next to the vector. Python's bundled SQLite (3.54) loads the extension.

## Consequences

- The VectorStore port gains `delete(collection, ids)` so removing a document removes its chunks; the contract test covers it. Phase 4's AWS adapter implements it too.
- Collections: `docs:{userId}` for document chunks, `cards:{sessionId}` for prepared questions (Phase 2P).
- Vector size is fixed by the first insert; changing the embedding model means re-embedding, which Step P.1 will offer as "rebuild".
- Brute force search inside SQLite is fine at this size; a few thousand vectors answer in milliseconds.
