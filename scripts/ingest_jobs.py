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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and materialize job postings dataset.")
    parser.add_argument(
        "--input",
        default="data/job_postings.json",
        help="Input dataset file (.json or .jsonl).",
    )
    parser.add_argument(
        "--output",
        default="data/job_postings.json",
        help="Output normalized dataset file (.json).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    payload = _load_input(input_path)
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
