import re

from app.schemas.match import JobMatch, ResumeMatchResponse
from app.services.resume_service import ResumeService
from app.services.retrieval_service import RetrievalService


class MatchService:
    def __init__(
        self,
        resume_service: ResumeService = None,
        retrieval_service: RetrievalService = None,
    ) -> None:
        self.resume_service = resume_service or ResumeService()
        self.retrieval_service = retrieval_service or RetrievalService()

    def match_resume_to_jobs(self, resume_id: int) -> ResumeMatchResponse:
        resume = self.resume_service.get_resume_by_id(resume_id)
        resume_tokens = self._tokenize(resume["content"])
        retrieval_results = self.retrieval_service.search(str(resume["content"]))

        matches: list[JobMatch] = []
        for result in retrieval_results:
            job_tokens = self._tokenize(f"{result.title} {result.snippet}")
            matched_keywords = sorted(resume_tokens & job_tokens)
            if not matched_keywords:
                continue

            raw_score = min(100, 40 + (len(matched_keywords) * 15))
            matches.append(
                JobMatch(
                    job_title=result.title,
                    match_score=raw_score,
                    matched_keywords=matched_keywords,
                    rationale=(
                        "匹配关键词："
                        + "、".join(matched_keywords[:5])
                        + "，这些内容同时出现在你的简历和岗位信息中"
                    ),
                )
            )

        return ResumeMatchResponse(resume_id=resume_id, matches=matches)

    def _tokenize(self, text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
