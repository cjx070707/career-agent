"""Chroma-backed semantic index for conversation turns.

Phase 2 of the memory context budget: instead of only keyword-filtering
turns within the current session (Phase 1 / task_family), this service
embeds every saved turn and allows cross-session semantic recall at query
time.

Design goals
------------
* Best-effort — every public method swallows exceptions so the agent never
  crashes because of a vector-store failure.
* Reuses the same embedding function as RetrievalService (DashScope or
  LocalToken fallback), so there is only one embedding config in settings.
* Each user's turns are stored with a `user_id` metadata field and filtered
  at query time, so users never see each other's history.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.api.types import EmbeddingFunction

from app.env import settings
from app.services.retrieval_service import (
    DashScopeEmbeddingFunction,
    LocalTokenEmbeddingFunction,
)

logger = logging.getLogger(__name__)


class MemoryVectorService:
    """Semantic index of past conversation turns.

    Public API
    ----------
    index_turn(turn_id, user_id, session_id, role, content)
        Embed and upsert a single turn.  Call from the post-turn
        background-task section (best-effort, exceptions are swallowed).

    search(user_id, query, n_results, exclude_session) -> list[dict]
        Return the top-n turns semantically similar to *query* for
        *user_id*, optionally excluding the current session's turns
        (those are already handled by Phase 1).

    document_count(user_id) -> int
        Number of indexed turns for *user_id*.
    """

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        directory = persist_directory or Path(settings.chroma_persist_directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(directory))
        self._embedding_fn: EmbeddingFunction = self._build_embedding_function()
        coll_name = collection_name or settings.memory_collection_name
        self._collection = self._get_or_create_collection(coll_name)

    # ── Embedding ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_embedding_function() -> EmbeddingFunction:
        if settings.embedding_api_key:
            return DashScopeEmbeddingFunction(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )
        return LocalTokenEmbeddingFunction()

    def _get_or_create_collection(self, name: str):
        try:
            return self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_fn,
            )
        except Exception:
            try:
                self._client.delete_collection(name)
            except Exception:
                pass
            return self._client.create_collection(
                name=name,
                embedding_function=self._embedding_fn,
            )

    # ── Write ─────────────────────────────────────────────────────────────

    def index_turn(
        self,
        *,
        turn_id: int,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Embed and upsert a conversation turn.  Silently skips empty content."""
        if not content or not content.strip():
            return
        doc_id = f"{user_id}__{turn_id}"
        try:
            self._collection.upsert(
                ids=[doc_id],
                documents=[content.strip()],
                metadatas=[
                    {
                        "user_id": user_id,
                        "session_id": session_id or "",
                        "role": role,
                        "turn_id": turn_id,
                    }
                ],
            )
        except Exception as exc:
            logger.debug("memory_vector index_turn failed (turn_id=%s): %s", turn_id, exc)

    # ── Read ──────────────────────────────────────────────────────────────

    def search(
        self,
        user_id: str,
        query: str,
        n_results: int = 2,
        exclude_session: Optional[str] = None,
    ) -> list[dict]:
        """Return up to *n_results* turns semantically similar to *query*.

        Parameters
        ----------
        user_id:
            Only returns turns belonging to this user.
        query:
            The current user message (embedded on the fly).
        n_results:
            Maximum number of results.
        exclude_session:
            When set, turns from this session are excluded (they are already
            handled by Phase 1 keyword filtering for the current session).

        Returns a list of dicts with keys ``role`` and ``content``.
        Returns ``[]`` on any error.
        """
        if not query or not query.strip():
            return []
        try:
            # Build where filter
            if exclude_session:
                where: dict = {
                    "$and": [
                        {"user_id": {"$eq": user_id}},
                        {"session_id": {"$ne": exclude_session}},
                    ]
                }
            else:
                where = {"user_id": {"$eq": user_id}}

            # Chroma raises if n_results > collection size
            total = self.document_count(user_id)
            if total == 0:
                return []
            safe_n = min(n_results, total)

            results = self._collection.query(
                query_texts=[query.strip()],
                n_results=safe_n,
                where=where,
                include=["documents", "metadatas"],
            )

            hits = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            for doc, meta in zip(docs, metas):
                if doc:
                    hits.append({"role": meta.get("role", "user"), "content": doc})
            return hits
        except Exception as exc:
            logger.debug("memory_vector search failed (user_id=%s): %s", user_id, exc)
            return []

    def document_count(self, user_id: str) -> int:
        """Number of indexed turns for *user_id*."""
        try:
            result = self._collection.get(where={"user_id": {"$eq": user_id}}, include=[])
            return len(result.get("ids", []))
        except Exception:
            return 0
