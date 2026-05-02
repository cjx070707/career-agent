"""JobProvider protocol — any job source must implement this interface."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class JobProvider(Protocol):
    def fetch_jobs(self, query: str, location: str, max_results: int) -> list[dict]:
        """Return a list of job dicts conforming to the JobPosting schema in ingest_jobs.py."""
        ...
