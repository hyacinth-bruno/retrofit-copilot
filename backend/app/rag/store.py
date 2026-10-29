"""Hybrid retrieval over the knowledge base with Qdrant.

- Dense vectors: multilingual sentence embeddings (fastembed, runs locally, no API cost).
- Sparse vectors: BM25-style term weights; Qdrant applies IDF on the server.
- The two result lists are merged with Reciprocal Rank Fusion (RRF).

Dense search finds paraphrases ("grant for insulation" ~ "Zuschuss Dämmung").
Sparse search finds exact terms that embeddings blur ("iSFP", "KfW 458", "§ 559").
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.config import get_settings

log = logging.getLogger(__name__)

STOPWORDS = set(
    "the a an and or of to in for on is are be with by as at from that this it its can if "
    "der die das und oder ein eine für mit von zu im in ist sind bei auf den dem des".split()
)


# ---------- embeddings ----------


class HashEmbedder:
    """Deterministic offline embedding. Used in tests and CI, not for real quality."""

    dim = 256

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in tokenize(text):
            v[zlib.crc32(tok.encode()) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FastEmbedder:
    def __init__(self, model: str):
        from fastembed import TextEmbedding

        self._m = TextEmbedding(model_name=model)
        self.dim = len(next(iter(self._m.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._m.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._m.embed([text]))).tolist()


def make_embedder():
    s = get_settings()
    if s.embedding_backend == "fastembed":
        try:
            return FastEmbedder(s.embedding_model), "fastembed"
        except Exception as exc:  # model download blocked, no internet, etc.
            log.warning("fastembed unavailable (%s); falling back to hash embeddings", exc)
    return HashEmbedder(), "hash"


# ---------- sparse ----------


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-zäöüß0-9§+]+", text.lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


def sparse_vector(text: str) -> qm.SparseVector:
    counts = Counter(tokenize(text))
    idx: dict[int, float] = {}
    for tok, tf in counts.items():
        i = zlib.crc32(tok.encode()) & 0x7FFFFFFF
        idx[i] = idx.get(i, 0.0) + 1.0 + math.log(tf)
    return qm.SparseVector(indices=list(idx.keys()), values=list(idx.values()))


# ---------- chunking ----------


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    url: str | None
    text: str


def chunk_markdown(path: Path, max_chars: int = 900) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    doc_id = path.stem
    title = next((ln[2:].strip() for ln in raw.splitlines() if ln.startswith("# ")), doc_id)
    url_m = re.search(r"^Source:\s*(\S+)", raw, re.MULTILINE)
    url = url_m.group(1) if url_m else None

    sections: list[tuple[str, str]] = []
    current, buf = title, []
    for line in raw.splitlines():
        if line.startswith("## "):
            if buf:
                sections.append((current, "\n".join(buf).strip()))
            current, buf = line[3:].strip(), []
        elif not line.startswith("# ") and not line.startswith("Source:"):
            buf.append(line)
    if buf:
        sections.append((current, "\n".join(buf).strip()))

    chunks: list[Chunk] = []
    for section, body in sections:
        if not body:
            continue
        paras, piece = [p for p in body.split("\n\n") if p.strip()], ""
        for para in paras:
            if piece and len(piece) + len(para) > max_chars:
                chunks.append(Chunk("", doc_id, title, section, url, piece.strip()))
                piece = ""
            piece += para + "\n\n"
        if piece.strip():
            chunks.append(Chunk("", doc_id, title, section, url, piece.strip()))
    for i, c in enumerate(chunks):
        c.chunk_id = f"{doc_id}#{i}"
    return chunks


# ---------- store ----------


@dataclass
class Hit:
    chunk_id: str
    title: str
    section: str
    url: str | None
    text: str
    score: float


class KnowledgeStore:
    def __init__(self):
        s = get_settings()
        self.collection = s.qdrant_collection
        self.embedder, self.embedding_backend = make_embedder()
        try:
            self.client = QdrantClient(url=s.qdrant_url, timeout=3, check_compatibility=False)
            self.client.get_collections()
            self.mode = "server"
        except Exception:
            log.warning("Qdrant server not reachable at %s; using in-memory Qdrant", s.qdrant_url)
            self.client = QdrantClient(":memory:")
            self.mode = "memory"
        self.chunks: dict[str, Chunk] = {}
        self.kb_version = ""

    def ingest(self, folder: Path) -> int:
        files = sorted(folder.glob("*.md"))
        chunks = [c for f in files for c in chunk_markdown(f)]
        self.kb_version = hashlib.sha256(b"".join(f.read_bytes() for f in files)).hexdigest()[:10]
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection,
            vectors_config={
                "dense": qm.VectorParams(size=self.embedder.dim, distance=qm.Distance.COSINE)
            },
            sparse_vectors_config={"bm25": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
        )
        texts = [f"{c.title} — {c.section}\n{c.text}" for c in chunks]
        dense = self.embedder.embed_documents(texts)
        points = [
            qm.PointStruct(
                id=i,
                vector={"dense": dense[i], "bm25": sparse_vector(texts[i])},
                payload={
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "title": c.title,
                    "section": c.section,
                    "url": c.url,
                    "text": c.text,
                    "kb_version": self.kb_version,
                },
            )
            for i, c in enumerate(chunks)
        ]
        self.client.upsert(self.collection, points=points, wait=True)
        self.chunks = {c.chunk_id: c for c in chunks}
        return len(chunks)

    def search(self, query: str, k: int | None = None, mode: str = "hybrid") -> list[Hit]:
        k = k or get_settings().retrieval_top_k
        dense_q = self.embedder.embed_query(query)
        sparse_q = sparse_vector(query)
        if mode == "dense":
            res = self.client.query_points(self.collection, query=dense_q, using="dense", limit=k)
        elif mode == "sparse":
            res = self.client.query_points(self.collection, query=sparse_q, using="bm25", limit=k)
        else:
            res = self.client.query_points(
                self.collection,
                prefetch=[
                    qm.Prefetch(query=dense_q, using="dense", limit=20),
                    qm.Prefetch(query=sparse_q, using="bm25", limit=20),
                ],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=k,
                with_payload=True,
            )
        return [
            Hit(
                p.payload["chunk_id"],
                p.payload["title"],
                p.payload["section"],
                p.payload.get("url"),
                p.payload["text"],
                round(p.score, 4),
            )
            for p in res.points
        ]


_store: KnowledgeStore | None = None


def knowledge() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
        n = _store.ingest(get_settings().data_dir / "knowledge")
        log.info("Indexed %d chunks (%s, %s embeddings)", n, _store.mode, _store.embedding_backend)
    return _store
