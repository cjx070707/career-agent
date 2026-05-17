import re

from app.schemas.match import JobMatch, ResumeMatchResponse
from app.services.resume_service import ResumeService
from app.services.retrieval_service import RetrievalService

# Common English stop words + short noise tokens to exclude from keyword matching
_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "can", "s",
    "t", "it", "its", "this", "that", "we", "you", "he", "she", "they", "i",
    "me", "my", "your", "our", "their", "as", "if", "so", "not", "no",
    "inc", "co", "ltd", "llc", "job", "position", "role", "location",
    "new", "other", "also", "all", "more", "some", "such", "than", "then",
    "when", "where", "which", "who", "how", "what", "any", "each", "both",
}


class MatchService:
    def __init__(
        self,
        resume_service: ResumeService = None,
        retrieval_service: RetrievalService = None,
    ) -> None:
        self.resume_service = resume_service or ResumeService()
        self.retrieval_service = retrieval_service or RetrievalService()

    # ChromaDB uses L2 (Euclidean) distance by default.
    # For normalized embeddings: cosine_sim = 1 - L2_dist² / 2
    # Observed range for DashScope text-embedding-v3:
    #   good match  → dist ~0.77  → cosine ~0.70
    #   weak match  → dist ~0.85  → cosine ~0.64
    #   poor match  → dist ~1.10  → cosine ~0.40
    # Map cosine [LOW, HIGH] → display score [0, 100]
    _SCORE_LOW = 0.55
    _SCORE_HIGH = 0.75

    def match_resume_to_jobs(self, resume_id: int) -> ResumeMatchResponse:
        resume = self.resume_service.get_resume_by_id(resume_id)
        resume_tokens = self._tokenize(resume["content"])
        scored_results = self.retrieval_service.search_jobs_with_scores(
            str(resume["content"]), n_results=10
        )

        matches: list[JobMatch] = []
        seen_titles: set[str] = set()
        for result, distance in scored_results:
            if result.title in seen_titles:
                continue
            seen_titles.add(result.title)

            # Keyword matching — display only, not used for scoring
            job_tokens = self._tokenize(f"{result.title} {result.snippet}")
            matched_keywords = sorted(resume_tokens & job_tokens)

            # ChromaDB returns L2 distance; convert to cosine similarity for normalized embeddings
            # cosine_sim = 1 - L2_dist² / 2
            similarity = 1.0 - (distance ** 2) / 2.0
            raw = (similarity - self._SCORE_LOW) / (self._SCORE_HIGH - self._SCORE_LOW)
            match_score = round(max(0, min(100, raw * 100)))

            # Skip results with near-zero relevance
            if match_score < 5:
                continue

            matches.append(
                JobMatch(
                    job_title=result.title,
                    match_score=match_score,
                    matched_keywords=matched_keywords[:6],
                    rationale=(
                        "匹配关键词："
                        + "、".join(matched_keywords[:5])
                        + "，这些内容同时出现在你的简历和岗位信息中"
                        if matched_keywords
                        else "基于语义相似度匹配"
                    ),
                )
            )

        # Sort by score descending, return top 3
        matches.sort(key=lambda m: m.match_score, reverse=True)
        return ResumeMatchResponse(resume_id=resume_id, matches=matches[:3])

    def _tokenize(self, text: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", text.lower())  # min 3 chars, starts with letter
        return {t for t in tokens if t not in _STOP_WORDS}
