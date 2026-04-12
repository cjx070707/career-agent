from pathlib import Path
from uuid import uuid4

import pytest

from app.db.session import init_db
from app.env import settings


@pytest.fixture
def isolated_runtime(tmp_path: Path):
    original_db_path = settings.db_path
    original_chroma_persist_directory = settings.chroma_persist_directory
    original_chroma_collection_name = settings.chroma_collection_name
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key

    db_path = tmp_path / "test.db"
    chroma_path = tmp_path / "chroma"
    collection_name = f"test_jobs_{uuid4().hex}"

    settings.db_path = str(db_path)
    settings.chroma_persist_directory = str(chroma_path)
    settings.chroma_collection_name = collection_name
    settings.openai_api_key = ""
    settings.planner_api_key = ""
    init_db(str(db_path))

    try:
        yield {
            "db_path": db_path,
            "chroma_path": chroma_path,
            "collection_name": collection_name,
        }
    finally:
        settings.db_path = original_db_path
        settings.chroma_persist_directory = original_chroma_persist_directory
        settings.chroma_collection_name = original_chroma_collection_name
        settings.openai_api_key = original_openai_api_key
        settings.planner_api_key = original_planner_api_key
