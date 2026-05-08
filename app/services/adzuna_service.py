"""Adzuna Jobs API client.

Fetches real job postings from Adzuna Australia and normalises them
to the JobPosting schema used by ingest_jobs.py / RetrievalService.

API docs: https://developer.adzuna.com/
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import requests

from app.env import settings


@runtime_checkable
class JobProvider(Protocol):
    """Any job source (Adzuna, mock, etc.) must implement this interface."""
    def fetch_jobs(self, query: str, location: str, max_results: int) -> list[dict]:
        """Return a list of job dicts conforming to the JobPosting schema."""
        ...

_BASE_URL = "https://api.adzuna.com/v1/api/jobs/au/search"
_DEFAULT_TIMEOUT = 10.0


class AdzunaService:
    def __init__(self, app_id: str = "", api_key: str = "") -> None:
        self._app_id = app_id or settings.adzuna_app_id
        self._api_key = api_key or settings.adzuna_api_key
        if not self._app_id or not self._api_key:
            raise ValueError("ADZUNA_APP_ID and ADZUNA_API_KEY must be set in .env")

    def fetch_jobs(self, query: str, location: str = "Sydney", max_results: int = 50) -> list[dict]:
        """Fetch jobs from Adzuna and return normalised JobPosting dicts."""
        results: list[dict] = []
        page = 1
        per_page = min(max_results, 50)  # Adzuna max per page is 50

        while len(results) < max_results:
            data = self._fetch_page(query, location, page, per_page)
            jobs = data.get("results", [])
            if not jobs:
                break
            for job in jobs:
                results.append(self._normalise(job))
                if len(results) >= max_results:
                    break
            if len(jobs) < per_page:
                break
            page += 1

        return results

    def _fetch_page(self, query: str, location: str, page: int, per_page: int) -> dict[str, Any]:
        params = {
            "app_id": self._app_id,
            "app_key": self._api_key,
            "results_per_page": per_page,
            "what": query,
            "where": location,
            "content-type": "application/json",
        }
        resp = requests.get(f"{_BASE_URL}/{page}", params=params, timeout=_DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _normalise(job: dict[str, Any]) -> dict:
        # Parse posted date
        created = job.get("created", "")
        try:
            posted_at = datetime.fromisoformat(created.replace("Z", "+00:00")).date().isoformat()
        except (ValueError, AttributeError):
            posted_at = None

        # Extract tags from category and contract type
        tags: list[str] = []
        category = job.get("category", {}).get("label", "")
        if category:
            tags.append(category.lower())
        contract_type = job.get("contract_type", "")
        if contract_type:
            tags.append(contract_type.lower())

        # Map Adzuna contract_time to work_type
        contract_time = job.get("contract_time", "")
        work_type_map = {"full_time": "full-time", "part_time": "part-time"}
        work_type = work_type_map.get(contract_time, contract_time or None)
        # Adzuna doesn't have an explicit "intern" field — infer from title/description
        title = job.get("title", "")
        description = job.get("description", "")
        if any(kw in (title + description).lower() for kw in ("intern", "internship", "graduate")):
            work_type = "intern"

        return {
            "type": "job_posting",
            "title": title,
            "snippet": description[:300] if description else "",
            "company": job.get("company", {}).get("display_name"),
            "location": job.get("location", {}).get("display_name"),
            "work_type": work_type,
            "posted_at": posted_at,
            "url": job.get("redirect_url"),
            "tags": tags,
        }
