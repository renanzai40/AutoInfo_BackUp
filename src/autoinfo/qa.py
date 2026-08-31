"""Q&A on collected content using FTS5 + LLM synthesis.

Provides :func:`query_collected` which searches the knowledge base using FTS5
full-text search, retrieves the top relevant entries, and synthesises an answer
via LLM with source citations.

No conversation persistence — every call is stateless.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from autoinfo.config import get_config_path, load_config
from autoinfo.kb import KBStore
from autoinfo.llm import call_with_fallback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "openai/ark-code-latest"


def query_collected(
    query: str,
    domain: str,
    content_ids: list[str] | None = None,
    store: KBStore | None = None,
) -> dict[str, Any]:
    """Search collected content and synthesise an answer via LLM.

    Parameters
    ----------
    query:
        The user's natural-language question.
    domain:
        Domain to scope the search to (e.g. ``"medical-research"``).
    content_ids:
        Optional explicit list of entry IDs to use instead of FTS5 search.
        When provided, FTS5 search is skipped and only these entries are
        used.
    store:
        Optional :class:`KBStore` instance for dependency injection in
        tests.  Defaults to a new ``KBStore()``.

    Returns
    -------
    dict
        ``{answer: str, sources: list[{entry_id: str, title: str}]}``

        *answer* is the LLM-generated response with ``[1]``, ``[2]`` source
        citations.  *sources* lists the entries that were used as context.

    Examples
    --------
    >>> result = query_collected("What are the latest IVF breakthroughs?",
    ...                          domain="medical-research")
    >>> result["answer"]
    'According to [1], time-lapse imaging improves live birth rates ...'
    >>> result["sources"]
    [{"entry_id": "entry-001", "title": "Improved IVF outcomes ..."}]
    """
    if store is None:
        store = KBStore()

    # ------------------------------------------------------------------
    # Step 1 — Retrieve relevant entries
    # ------------------------------------------------------------------
    raw_entries: list[dict[str, Any]] = []

    if content_ids:
        # Use explicitly-provided entry IDs
        for cid in content_ids:
            entry = store.get_entry(cid)
            if entry is not None:
                raw_entries.append(entry)
    else:
        # FTS5 search, top 5
        search_result = store.search_knowledge_base(
            query=query, domain=domain, limit=5
        )
        fts5_entries = search_result.get("entries", [])
        # Fetch full content for each FTS5 result
        for e in fts5_entries:
            full = store.get_entry(e["entry_id"])
            raw_entries.append(full if full is not None else e)

    # ------------------------------------------------------------------
    # Step 2 — Build source list and article context for the LLM
    # ------------------------------------------------------------------
    sources: list[dict[str, str]] = []
    articles_text: list[str] = []

    for i, entry in enumerate(raw_entries[:5]):
        entry_id = entry.get("entry_id", "")
        title = entry.get("title", "")

        # Use full content when available, fall back to summary
        body = entry.get("content", "") or entry.get("summary", "") or ""
        snippet = body[:2000] if body else ""

        sources.append({"entry_id": entry_id, "title": title})
        articles_text.append(f"[{i + 1}] {title}\n{snippet}\n")

    # ------------------------------------------------------------------
    # Step 3 — LLM synthesis
    # ------------------------------------------------------------------
    if not sources:
        return {
            "answer": (
                "No relevant articles found in the knowledge base to "
                "answer your question."
            ),
            "sources": [],
        }

    answer = _call_llm_for_qa(query, articles_text)

    return {"answer": answer, "sources": sources}


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _call_llm_for_qa(query: str, articles: list[str]) -> str:
    """Send the question and article context to the LLM and return the answer.

    Parameters
    ----------
    query:
        The user's question.
    articles:
        Formatted article strings, each prefixed with ``[N]``.

    Returns
    -------
    str
        The LLM's answer text, or an error message if the call fails.
    """
    # Resolve the effective model + configure API key from config
    full_model = _resolve_model()

    system_prompt = (
        "You are AutoInfo, a research assistant. "
        "Answer the user's question based ONLY on the provided articles. "
        "Cite sources using [1], [2], etc. "
        "Do not reference any external knowledge or make up information. "
        "If the articles do not contain enough information to answer the "
        "question fully, state that clearly."
    )

    articles_joined = "\n\n---\n\n".join(articles)

    user_prompt = (
        f"Question: {query}\n\n"
        f"Articles:\n\n{articles_joined}\n\n"
        "Please answer the question based only on these articles."
    )

    try:
        response = call_with_fallback(
            model=full_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=2000,
            temperature=0.1,
        )
        content: str = response.choices[0].message.content  # type: ignore[union-attr]
        return content or ""
    except Exception as exc:
        logger.error("LLM Q&A call failed: %s", exc)
        return (
            f"An error occurred while contacting the LLM: {exc}. "
            "Please check your LLM configuration and try again."
        )


def _resolve_model() -> str:
    """Read LLM provider/model from config and set the API key env var.

    Returns the full model string (e.g. ``"openrouter/deepseek/deepseek-chat"``).
    """
    try:
        config_path = get_config_path()
        if config_path is not None:
            config = load_config(config_path)
            provider = config.llm.provider or DEFAULT_PROVIDER
            model = config.llm.model or DEFAULT_MODEL
            if config.llm.api_key:
                env_key = f"{provider.upper()}_API_KEY"
                os.environ.setdefault(env_key, config.llm.api_key)
            if "/" not in model:
                return f"{provider}/{model}"
            return model
    except Exception:
        logger.warning("Failed to load LLM config, using defaults")
    return f"{DEFAULT_PROVIDER}/{DEFAULT_MODEL}"
