import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.planner_debug import run_full_eval_debug, run_single_plan_debug


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug planner outputs.")
    parser.add_argument(
        "--mode",
        choices=["single", "eval"],
        default="single",
        help="Run one planner request or the full eval suite.",
    )
    parser.add_argument("--message", default="帮我找一些岗位")
    args = parser.parse_args()

    if args.mode == "eval":
        print(run_full_eval_debug())
        return

    print(
        run_single_plan_debug(
            {
                "message": args.message,
                "memory_context": [],
                "profile": {},
                "available_tools": [
                    "get_candidate_profile",
                    "get_resume_by_id",
                    "search_jobs",
                    "match_resume_to_jobs",
                ],
                "user_state": {"has_candidate": True, "has_resume": True},
            }
        )
    )


if __name__ == "__main__":
    main()
