import os
from pathlib import Path

from pydantic import BaseModel


def load_dotenv_values(dotenv_path: Path = None) -> dict[str, str]:
    path = dotenv_path or Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


DOTENV_VALUES = load_dotenv_values()


def get_setting(name: str, default: str) -> str:
    return os.getenv(name, DOTENV_VALUES.get(name, default))


def get_bool_setting(name: str, default: bool) -> bool:
    raw = os.getenv(name, DOTENV_VALUES.get(name))
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    app_name: str = "Career Agent Backend"
    app_version: str = "0.1.0"
    openai_api_key: str = get_setting("OPENAI_API_KEY", "")
    openai_base_url: str = get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1")
    default_model: str = get_setting("DEFAULT_MODEL", "gpt-4.1-mini")
    planner_api_key: str = get_setting("PLANNER_API_KEY", get_setting("OPENAI_API_KEY", ""))
    planner_base_url: str = get_setting("PLANNER_BASE_URL", get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    planner_model: str = get_setting("PLANNER_MODEL", get_setting("DEFAULT_MODEL", "gpt-4.1-mini"))
    planner_disable_thinking: bool = get_bool_setting("PLANNER_DISABLE_THINKING", False)
    vision_api_key: str = get_setting(
        "VISION_API_KEY",
        get_setting("PLANNER_API_KEY", get_setting("OPENAI_API_KEY", "")),
    )
    vision_base_url: str = get_setting(
        "VISION_BASE_URL",
        get_setting(
            "PLANNER_BASE_URL",
            get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ),
    )
    vision_model: str = get_setting("VISION_MODEL", "qwen3-vl-flash-2026-01-22")
    db_path: str = get_setting("DB_PATH", "data/career_agent.db")
    job_postings_file: str = get_setting("JOB_POSTINGS_FILE", "data/job_postings.json")
    chroma_persist_directory: str = get_setting("CHROMA_PERSIST_DIRECTORY", "data/chroma")
    chroma_collection_name: str = get_setting("CHROMA_COLLECTION_NAME", "job_postings_v2")


settings = Settings()
