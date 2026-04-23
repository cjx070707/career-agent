import json
import re
from dataclasses import dataclass, field
from hashlib import md5
from pathlib import Path
from typing import Optional, Sequence

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
    company: Optional[str] = None
    location: Optional[str] = None
    work_type: Optional[str] = None
    posted_at: Optional[str] = None
    url: Optional[str] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ReasonedJobHit:
    type: str
    title: str
    snippet: str
    company: Optional[str]
    location: Optional[str]
    work_type: Optional[str]
    posted_at: Optional[str]
    url: Optional[str]
    tags: list[str]
    matched_terms: list[str]
    reason: str


_MAX_MATCHED_TERMS = 3
_GENERIC_MATCH_TERMS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "developer",
        "developers",
        "engineer",
        "engineers",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "intern",
        "interns",
        "internship",
        "is",
        "it",
        "its",
        "job",
        "jobs",
        "may",
        "might",
        "must",
        "of",
        "on",
        "or",
        "position",
        "positions",
        "role",
        "roles",
        "should",
        "software",
        "team",
        "teams",
        "that",
        "the",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "will",
        "with",
        "work",
        "works",
        "would",
    }
)


class RetrievalService:
    """ChromaDB-backed retrieval over local job posting data."""

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        corpus_path = Path(settings.job_postings_file)
        if not corpus_path.is_absolute():
            corpus_path = Path(__file__).resolve().parents[2] / corpus_path
        with corpus_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._job_postings = [self._to_retrieval_result(item) for item in payload]
        self._persist_directory = persist_directory or self._resolve_default_persist_directory()
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=collection_name or settings.chroma_collection_name,
            embedding_function=LocalTokenEmbeddingFunction(),
        )
        self._seed_collection()

    def search(self, query: str) -> list[RetrievalResult]:
        return self._search_ranked(query)

    def search_with_reasons(self, query: str) -> list[ReasonedJobHit]:
        ranked = self._search_ranked(query)
        return [self._to_reasoned_hit(query, hit) for hit in ranked]

    def _search_ranked(self, query: str) -> list[RetrievalResult]:
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
                company=metadata.get("company") or None,
                location=metadata.get("location") or None,
                work_type=metadata.get("work_type") or None,
                posted_at=metadata.get("posted_at") or None,
                url=metadata.get("url") or None,
                tags=self._parse_tags(metadata.get("tags") or ""),
            )
            for metadata in metadatas
        ]
        return self._rerank(query, results)

    def _to_reasoned_hit(self, query: str, hit: RetrievalResult) -> ReasonedJobHit:
        # Retrieval owns ranking plus grounded evidence, not final user-facing prose.
        matched_terms = self._matched_terms(query, hit.title, hit.snippet)
        reason = self._reason_text(query, hit, matched_terms)
        return ReasonedJobHit(
            type=hit.type,
            title=hit.title,
            snippet=hit.snippet,
            company=hit.company,
            location=hit.location,
            work_type=hit.work_type,
            posted_at=hit.posted_at,
            url=hit.url,
            tags=hit.tags,
            matched_terms=matched_terms,
            reason=reason,
        )

    def _matched_terms(self, query: str, title: str, snippet: str) -> list[str]:
        doc_tokens = self._tokenize(f"{title} {snippet}")
        matched_terms: list[str] = []
        for token in self._ordered_tokens(query):
            if token in _GENERIC_MATCH_TERMS:
                continue
            if token not in doc_tokens:
                continue
            matched_terms.append(token)
            if len(matched_terms) == _MAX_MATCHED_TERMS:
                break
        return matched_terms

    def _reason_text(
        self,
        query: str,
        hit: RetrievalResult,
        matched_terms: Sequence[str],
    ) -> str:
        if matched_terms:
            return f"命中关键词：{'、'.join(matched_terms)}。{self._format_job_context(hit)}"
        body_tokens = self._tokenize(f"{hit.title} {hit.snippet}")
        query_tokens = self._tokenize(query)
        if query_tokens & body_tokens:
            return (
                "命中关键词：仅匹配到低信号通用词，排序仍依据标题与摘要中的词面重合度。"
                f"{self._format_job_context(hit)}"
            )
        return (
            "未命中显性关键词；排序依据为语义向量与职位标题及摘要的相关性。"
            f"{self._format_job_context(hit)}"
        )

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
                    "company": posting.company or "",
                    "location": posting.location or "",
                    "work_type": posting.work_type or "",
                    "posted_at": posting.posted_at or "",
                    "url": posting.url or "",
                    "tags": ",".join(posting.tags or []),
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
        zero_score_results: list[RetrievalResult] = []
        for candidate in candidates:
            body_tokens = self._tokenize(f"{candidate.title} {candidate.snippet}")
            overlap = len(query_tokens & body_tokens)
            title_overlap = len(query_tokens & self._tokenize(candidate.title))
            score = overlap + (title_overlap * 2)
            if score > 0:
                scored_results.append((score, candidate))
            else:
                zero_score_results.append(candidate)

        if not scored_results:
            return candidates

        scored_results.sort(key=lambda item: (-item[0], item[1].title))
        return [candidate for _, candidate in scored_results] + zero_score_results

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

    def _ordered_tokens(self, text: str) -> list[str]:
        ordered_tokens: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[a-zA-Z0-9]+", text.lower()):
            if token in seen:
                continue
            seen.add(token)
            ordered_tokens.append(token)
        return ordered_tokens

    def _resolve_default_persist_directory(self) -> Path:
        configured = Path(settings.chroma_persist_directory)
        if not configured.is_absolute():
            configured = Path(__file__).resolve().parents[2] / configured
        return configured

    def _to_retrieval_result(self, payload: dict) -> RetrievalResult:
        normalized = dict(payload)
        normalized["tags"] = list(payload.get("tags") or [])
        return RetrievalResult(**normalized)

    def _format_job_context(self, hit: RetrievalResult) -> str:
        parts: list[str] = []
        if hit.company:
            parts.append(f"公司：{hit.company}")
        if hit.location:
            parts.append(f"地点：{hit.location}")
        if hit.work_type:
            parts.append(f"类型：{hit.work_type}")
        if not parts:
            return ""
        return "（" + "，".join(parts) + "）"

    def _parse_tags(self, raw: str) -> list[str]:
        text = str(raw).strip()
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]
