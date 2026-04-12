import json
import re
from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from app.env import settings


class LocalTokenEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic local embedding to avoid external model dependencies."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        return "local-token-embedding"

    @staticmethod
    def get_config() -> dict[str, int]:
        return {"dimensions": 256}

    @classmethod
    def build_from_config(cls, config: dict[str, int]) -> "LocalTokenEmbeddingFunction":
        _ = config
        return cls()

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed_document(text) for text in input]

    def _embed_document(self, text: str) -> list[float]:
        vector = [0.0] * 256
        tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
        for token in tokens:
            index = int(md5(token.encode("utf-8")).hexdigest(), 16) % len(vector)
            vector[index] += 1.0
        norm = sum(value * value for value in vector) ** 0.5
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@dataclass
class RetrievalResult:
    type: str
    title: str
    snippet: str


class RetrievalService:
    """ChromaDB-backed retrieval over local job posting data."""

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        corpus_path = Path(__file__).resolve().parents[2] / "data" / "job_postings.json"
        with corpus_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._job_postings = [RetrievalResult(**item) for item in payload]
        self._persist_directory = persist_directory or self._resolve_default_persist_directory()
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.chroma_collection_name,
            embedding_function=LocalTokenEmbeddingFunction(),
        )
        self._seed_collection()

    def search(self, query: str) -> list[RetrievalResult]:
        if not query.strip():
            return []
        n_results = min(max(self._collection.count(), 3), 10)
        response = self._collection.query(query_texts=[query], n_results=n_results)
        metadatas = response.get("metadatas", [[]])[0]
        if not metadatas:
            return []

        results = [
            RetrievalResult(
                type=metadata["type"],
                title=metadata["title"],
                snippet=metadata["snippet"],
            )
            for metadata in metadatas
        ]
        return self._rerank(query, results)

    def document_count(self) -> int:
        return self._collection.count()

    def upsert_job(self, job_id: int, title: str) -> None:
        self._collection.upsert(
            ids=[f"db-job-{job_id}"],
            documents=[title],
            metadatas=[
                {
                    "type": "job_posting",
                    "title": title,
                    "snippet": title,
                }
            ],
        )

    def _seed_collection(self) -> None:
        if self._collection.count() > 0:
            return

        self._collection.add(
            ids=[f"job-{index}" for index, _ in enumerate(self._job_postings)],
            documents=[
                f"{posting.title}. {posting.snippet}" for posting in self._job_postings
            ],
            metadatas=[
                {
                    "type": posting.type,
                    "title": posting.title,
                    "snippet": posting.snippet,
                }
                for posting in self._job_postings
            ],
        )

    def _rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        query_tokens = self._tokenize(query)
        scored_results: list[tuple[int, RetrievalResult]] = []
        for candidate in candidates:
            body_tokens = self._tokenize(f"{candidate.title} {candidate.snippet}")
            overlap = len(query_tokens & body_tokens)
            title_overlap = len(query_tokens & self._tokenize(candidate.title))
            score = overlap + (title_overlap * 2)
            if score > 0:
                scored_results.append((score, candidate))

        scored_results.sort(key=lambda item: (-item[0], item[1].title))
        return [candidate for _, candidate in scored_results]

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

    def _resolve_default_persist_directory(self) -> Path:
        configured = Path(settings.chroma_persist_directory)
        if not configured.is_absolute():
            configured = Path(__file__).resolve().parents[2] / configured
        return configured
