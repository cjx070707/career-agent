from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError


class JobPosting(BaseModel):
    type: str = Field(default="job_posting")
    title: str
    snippet: str
    company: Optional[str] = None
    location: Optional[str] = None
    work_type: Optional[str] = None
    posted_at: Optional[str] = None
    url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


def _load_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(json.loads(line))
        return rows
    return json.loads(path.read_text(encoding="utf-8"))


def _summarize(rows: list[JobPosting]) -> str:
    by_work_type = Counter(item.work_type or "unknown" for item in rows)
    by_location = Counter(item.location or "unknown" for item in rows)
    lines = [f"total={len(rows)}", "work_type:"]
    lines.extend(f"  - {name}: {count}" for name, count in sorted(by_work_type.items()))
    lines.append("location:")
    lines.extend(f"  - {name}: {count}" for name, count in sorted(by_location.items()))
    return "\n".join(lines)


def _fetch_adzuna(query: str, location: str, max_results: int) -> list[dict[str, Any]]:
    from app.services.adzuna_service import AdzunaService
    svc = AdzunaService()
    print(f"Fetching up to {max_results} jobs from Adzuna: query={query!r} location={location!r}")
    return svc.fetch_jobs(query=query, location=location, max_results=max_results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and materialise job postings dataset.")
    parser.add_argument("--input", default="data/job_postings.json",
                        help="Input dataset file (.json or .jsonl). Ignored when --source=adzuna.")
    parser.add_argument("--output", default="data/job_postings.json",
                        help="Output normalised dataset file (.json).")
    parser.add_argument("--source", choices=["file", "adzuna"], default="file",
                        help="Data source: 'file' (default) reads --input; 'adzuna' fetches live data.")
    parser.add_argument("--query", default="intern Sydney",
                        help="Search query passed to Adzuna (only used with --source=adzuna).")
    parser.add_argument("--location", default="Sydney",
                        help="Location filter passed to Adzuna (only used with --source=adzuna).")
    parser.add_argument("--max-results", type=int, default=100,
                        help="Max jobs to fetch from Adzuna (only used with --source=adzuna).")
    args = parser.parse_args()

    output_path = Path(args.output)

    if args.source == "adzuna":
        payload = _fetch_adzuna(args.query, args.location, args.max_results)
    else:
        payload = _load_input(Path(args.input))

    validated: list[JobPosting] = []
    for index, row in enumerate(payload, start=1):
        try:
            validated.append(JobPosting.model_validate(row))
        except ValidationError as exc:
            raise SystemExit(f"invalid row #{index}: {exc}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([item.model_dump() for item in validated], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(_summarize(validated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
