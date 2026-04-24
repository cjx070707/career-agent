"""Pure, router-side extractor for `search_jobs` structured filters.

Stage B contract: turn a free-form user message into an optional
`{location, work_type}` dict that the tool layer forwards verbatim to the
retrieval service. Rules are deterministic; no LLM call. If nothing is
detected we return an empty dict so callers can pass `filters or None`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


# Each rule: (label used in dataset, ordered list of case-insensitive
# substrings to probe). The label maps to the canonical metadata value
# stored in `data/job_postings.json` so retrieval can do substring match.
_LOCATION_RULES: List[Tuple[str, List[str]]] = [
    ("Sydney", ["sydney", "悉尼"]),
    ("Melbourne", ["melbourne", "墨尔本"]),
    ("Remote (AU)", ["remote", "远程"]),
]

# Order matters: when multiple work_type keywords co-occur we prefer the
# one that appears earliest in the message, so users who type
# "intern 或 graduate" get `intern` rather than `graduate`.
_WORK_TYPE_RULES: List[Tuple[str, List[str]]] = [
    ("intern", ["intern", "internship", "实习"]),
    ("graduate", ["graduate", "grad program", "grad", "校招", "应届"]),
    ("fulltime", ["fulltime", "full-time", "full time", "全职"]),
    ("parttime", ["parttime", "part-time", "part time", "兼职"]),
]


def extract_filters(message: str) -> Dict[str, str]:
    """Return a structured filter dict derived from `message`.

    Keys are omitted when no signal is detected. The values match the
    canonical metadata stored alongside each job posting, so the retrieval
    layer can do a case-insensitive substring comparison without needing
    extra normalisation.
    """
    if not message:
        return {}

    lowered = message.lower()
    filters: Dict[str, str] = {}

    location = _match_first(lowered, _LOCATION_RULES)
    if location is not None:
        filters["location"] = location

    work_type = _match_first(lowered, _WORK_TYPE_RULES)
    if work_type is not None:
        filters["work_type"] = work_type

    return filters


def _match_first(
    lowered_message: str,
    rules: List[Tuple[str, List[str]]],
) -> Optional[str]:
    """Return the canonical label whose keyword appears earliest.

    We scan each rule's keywords against the lowered message and keep the
    earliest non-negative index. This gives "intern or graduate" → intern
    and "graduate or intern" → graduate deterministically.
    """
    best_index: Optional[int] = None
    best_label: Optional[str] = None
    for label, keywords in rules:
        for keyword in keywords:
            idx = lowered_message.find(keyword.lower())
            if idx == -1:
                continue
            if best_index is None or idx < best_index:
                best_index = idx
                best_label = label
    return best_label
