from pathlib import Path
from uuid import uuid4

import pytest

from app.db.session import init_db
from app.env import settings


@pytest.fixture(autouse=True)
def _no_external_embedding_calls():
    """Force local token embedding in every test — no DashScope calls.

    DashScope's embedding API is unavailable/unreliable in test environments.
    All retrieval tests use the local keyword-token fallback instead.
    Tests that verify semantic ranking quality should be explicit about
    needing a real embedding API and marked accordingly.
    """
    original = settings.embedding_api_key
    settings.embedding_api_key = ""
    yield
    settings.embedding_api_key = original


@pytest.fixture
def isolated_runtime(tmp_path: Path):
    """Full isolation fixture: separate DB, Chroma, and no external API calls.

    Clears all API keys to force local/mock behavior — avoids accidental
    DashScope / OpenAI calls and makes tests deterministic.
    """
    original_db_path = settings.db_path
    original_chroma_persist_directory = settings.chroma_persist_directory
    original_chroma_collection_name = settings.chroma_collection_name
    original_openai_api_key = settings.openai_api_key
    original_planner_api_key = settings.planner_api_key
    original_vision_api_key = settings.vision_api_key

    db_path = tmp_path / "test.db"
    chroma_path = tmp_path / "chroma"
    collection_name = f"test_jobs_{uuid4().hex}"

    settings.db_path = str(db_path)
    settings.chroma_persist_directory = str(chroma_path)
    settings.chroma_collection_name = collection_name
    settings.openai_api_key = ""
    settings.planner_api_key = ""
    settings.vision_api_key = ""
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
        settings.vision_api_key = original_vision_api_key
