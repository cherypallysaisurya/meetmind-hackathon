"""VectorStore adapter on sqlite-vec: one SQLite file, cosine distance, partitioned by collection,
metadata stored as JSON next to each vector. Decision 0006.

SQLite is synchronous, so calls run in a thread and share one connection under a lock.
The vector size is fixed by the first insert.
"""

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

import numpy as np
import sqlite_vec

from ...ports import Match, VectorStore


class SqliteVecStore(VectorStore):
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.lock = threading.Lock()
        self.dimensions = self._existing_dimensions()

    def _existing_dimensions(self) -> int | None:
        row = self.db.execute("select sql from sqlite_master where name = 'vectors'").fetchone()
        if not row:
            return None
        return int(row[0].split("float[")[1].split("]")[0])

    def _ensure_table(self, dimensions: int) -> None:
        if self.dimensions is None:
            self.db.execute(
                f"create virtual table vectors using vec0("
                f"id text primary key, collection text partition key, embedding float[{dimensions}] distance_metric=cosine, +metadata text)"
            )
            self.db.commit()
            self.dimensions = dimensions
        elif dimensions != self.dimensions:
            raise ValueError(f"vectors of {dimensions} numbers do not fit a store of {self.dimensions}: re-embed or use a new file")

    async def add(self, collection, ids, vectors, metadata):
        def work():
            with self.lock:
                self._ensure_table(len(vectors[0]))
                with self.db:
                    self.db.executemany("delete from vectors where id = ?", [(i,) for i in ids])
                    self.db.executemany(
                        "insert into vectors(id, collection, embedding, metadata) values (?, ?, ?, ?)",
                        [(i, collection, np.asarray(v, dtype=np.float32).tobytes(), json.dumps(m)) for i, v, m in zip(ids, vectors, metadata)],
                    )
        if ids:
            await asyncio.to_thread(work)

    async def search(self, collection, vector, limit):
        def work():
            with self.lock:
                if self.dimensions is None:
                    return []
                rows = self.db.execute(
                    "select id, distance, metadata from vectors where collection = ? and embedding match ? and k = ? order by distance",
                    (collection, np.asarray(vector, dtype=np.float32).tobytes(), limit),
                ).fetchall()
            return [Match(id=i, score=round(1.0 - distance, 4), metadata=json.loads(m)) for i, distance, m in rows]
        return await asyncio.to_thread(work)

    async def delete(self, collection, ids):
        def work():
            with self.lock, self.db:
                if self.dimensions is not None:
                    self.db.executemany("delete from vectors where id = ?", [(i,) for i in ids])
        await asyncio.to_thread(work)

    async def delete_collection(self, collection):
        def work():
            with self.lock, self.db:
                if self.dimensions is None:
                    return
                ids = [row[0] for row in self.db.execute("select id from vectors where collection = ?", (collection,))]
                self.db.executemany("delete from vectors where id = ?", [(i,) for i in ids])
        await asyncio.to_thread(work)
