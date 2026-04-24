import json
import math
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
_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60
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

    def search_with_reasons(
        self,
        query: str,
        filters: Optional[dict] = None,
    ) -> list[ReasonedJobHit]:
        ranked = self._search_ranked(query, filters=filters)
        return [self._to_reasoned_hit(query, hit) for hit in ranked]

    def _search_ranked(
        self,
        query: str,
        filters: Optional[dict] = None,
    ) -> list[RetrievalResult]:
        if not query.strip():
            return []
        # When filters are requested we sweep the whole collection so the
        # post-filter doesn't starve behind a short top-k window. Corpus is
        # small enough (tens of items) that this stays cheap.
        if filters:
            n_results = max(self._collection.count(), 1)
        else:
            n_results = min(max(self._collection.count(), 3), 10)
        vector_results = self._vector_search(query, n_results=n_results)
        lexical_candidates = self._all_indexed_results()
        lexical_results = self._bm25_rank(query, lexical_candidates)[:n_results]
        results = self._rrf_merge(
            vector_results=vector_results,
            lexical_results=lexical_results,
        )
        if not results:
            return []

        reranked = self._rerank(query, results)
        filtered = self._apply_filters(reranked, filters)
        if filters:
            return filtered
        return filtered[:n_results]

    def _apply_filters(
        self,
        results: list[RetrievalResult],
        filters: Optional[dict],
    ) -> list[RetrievalResult]:
        if not filters:
            return results
        location_q = str(filters.get("location") or "").strip().lower()
        work_type_q = str(filters.get("work_type") or "").strip().lower()
        if not location_q and not work_type_q:
            return results
        filtered: list[RetrievalResult] = []
        for result in results:
            if location_q:
                if not result.location or location_q not in result.location.lower():
                    continue
            if work_type_q:
                if not result.work_type or work_type_q not in result.work_type.lower():
                    continue
            filtered.append(result)
        return filtered

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

    def upsert_career_profile(self, user_id: str, profile: dict) -> None:
        snippet = self._career_profile_snippet(profile)
        if not snippet:
            return
        self._collection.upsert(
            ids=[f"career-profile-{user_id}"],
            documents=[snippet],
            metadatas=[
                {
                    "type": "career_profile",
                    "title": "Career Profile",
                    "snippet": snippet,
                    "company": "",
                    "location": "",
                    "work_type": "",
                    "posted_at": "",
                    "url": "",
                    "tags": "career_profile",
                }
            ],
        )

    def upsert_career_event(self, event: dict) -> None:
        summary = str(event.get("summary") or "").strip()
        title = str(event.get("title") or "Career Event").strip()
        event_id = int(event["id"])
        if not summary:
            return
        self._collection.upsert(
            ids=[f"career-event-{event_id}"],
            documents=[f"{title}. {summary}"],
            metadatas=[
                {
                    "type": "career_event",
                    "title": title,
                    "snippet": summary,
                    "company": "",
                    "location": "",
                    "work_type": "",
                    "posted_at": str(event.get("occurred_at") or ""),
                    "url": "",
                    "tags": str(event.get("event_type") or "career_event"),
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

    def _vector_search(
        self,
        query: str,
        n_results: int,
    ) -> list[RetrievalResult]:
        response = self._collection.query(query_texts=[query], n_results=n_results)
        metadatas = response.get("metadatas", [[]])[0]
        return [self._metadata_to_result(metadata) for metadata in metadatas]

    def _all_indexed_results(self) -> list[RetrievalResult]:
        response = self._collection.get(include=["metadatas"])
        metadatas = response.get("metadatas", [])
        return [self._metadata_to_result(metadata) for metadata in metadatas]

    def _metadata_to_result(self, metadata: dict) -> RetrievalResult:
        return RetrievalResult(
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

    def _bm25_rank(
        self,
        query: str,
        candidates: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        query_tokens = self._ordered_tokens(query)
        if not query_tokens or not candidates:
            return candidates

        doc_tokens = [
            self._ordered_document_tokens(candidate) for candidate in candidates
        ]
        avg_doc_length = sum(len(tokens) for tokens in doc_tokens) / len(doc_tokens)
        if avg_doc_length == 0:
            return candidates

        document_frequency: dict[str, int] = {}
        for tokens in doc_tokens:
            for token in set(tokens):
                document_frequency[token] = document_frequency.get(token, 0) + 1

        scored: list[tuple[float, int, RetrievalResult]] = []
        zero_score: list[tuple[int, RetrievalResult]] = []
        total_documents = len(candidates)
        for index, candidate in enumerate(candidates):
            tokens = doc_tokens[index]
            score = self._bm25_score(
                query_tokens=query_tokens,
                doc_tokens=tokens,
                document_frequency=document_frequency,
                total_documents=total_documents,
                avg_doc_length=avg_doc_length,
            )
            if score > 0:
                scored.append((score, index, candidate))
            else:
                zero_score.append((index, candidate))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [candidate for _, _, candidate in scored] + [
            candidate for _, candidate in zero_score
        ]

    def _bm25_score(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        document_frequency: dict[str, int],
        total_documents: int,
        avg_doc_length: float,
    ) -> float:
        if not doc_tokens:
            return 0.0
        term_frequency: dict[str, int] = {}
        for token in doc_tokens:
            term_frequency[token] = term_frequency.get(token, 0) + 1

        score = 0.0
        doc_length = len(doc_tokens)
        for token in query_tokens:
            frequency = term_frequency.get(token, 0)
            if frequency == 0:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1 + (total_documents - df + 0.5) / (df + 0.5))
            denominator = frequency + _BM25_K1 * (
                1 - _BM25_B + _BM25_B * (doc_length / avg_doc_length)
            )
            score += idf * ((frequency * (_BM25_K1 + 1)) / denominator)
        return score

    def _rrf_merge(
        self,
        vector_results: list[RetrievalResult],
        lexical_results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        scores: dict[tuple[str, str, str], float] = {}
        results_by_key: dict[tuple[str, str, str], RetrievalResult] = {}
        first_seen: dict[tuple[str, str, str], int] = {}

        for ranking in (vector_results, lexical_results):
            for rank, result in enumerate(ranking, start=1):
                key = self._result_key(result)
                if key not in results_by_key:
                    results_by_key[key] = result
                    first_seen[key] = len(first_seen)
                scores[key] = scores.get(key, 0.0) + (1 / (_RRF_K + rank))

        ordered_keys = sorted(
            scores,
            key=lambda key: (-scores[key], first_seen[key]),
        )
        return [results_by_key[key] for key in ordered_keys]

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

    def _ordered_document_tokens(self, hit: RetrievalResult) -> list[str]:
        return re.findall(
            r"[a-zA-Z0-9]+",
            f"{hit.title} {hit.snippet} {' '.join(hit.tags)}".lower(),
        )

    def _result_key(self, result: RetrievalResult) -> tuple[str, str, str]:
        return (result.type, result.title, result.snippet)

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

    def _career_profile_snippet(self, profile: dict) -> str:
        parts: list[str] = []
        role = str(profile.get("target_role_preference") or "").strip()
        if role:
            parts.append(f"Target role: {role}")
        skills = profile.get("skill_keywords") or []
        if skills:
            parts.append("Skills: " + ", ".join(str(item) for item in skills))
        for key, label in (
            ("career_focus_notes", "Focus notes"),
            ("application_patterns", "Application patterns"),
            ("interview_weaknesses", "Interview weaknesses"),
            ("next_focus_areas", "Next focus areas"),
        ):
            value = str(profile.get(key) or "").strip()
            if value:
                parts.append(f"{label}: {value}")
        return ". ".join(parts)
