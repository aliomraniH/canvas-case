"""Search is token-AND substring: every whitespace token must appear, order-independent.

Regression for the bug where a single contiguous ILIKE made multi-word queries
(e.g. "field_names false negative") miss values that contained all the words.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DATABASE_URL") is None, reason="DATABASE_URL not set"
)


async def test_search_matches_tokens_out_of_order(backend, ns):
    await backend.memory_save(ns, "k", {"text": "alpha beta gamma"})
    hits = await backend.memory_search("gamma alpha", namespace=ns)  # was [] before the fix
    assert any("alpha beta gamma" in str(h["value"]) for h in hits)


async def test_search_requires_all_tokens(backend, ns):
    await backend.memory_save(ns, "k", {"text": "alpha beta gamma"})
    assert await backend.memory_search("alpha delta", namespace=ns) == []


async def test_search_empty_query_returns_empty(backend, ns):
    await backend.memory_save(ns, "k", {"text": "alpha"})
    assert await backend.memory_search("   ", namespace=ns) == []


async def test_search_excludes_tombstoned(backend, ns):
    await backend.memory_save(ns, "k", {"text": "titration schedule"})
    await backend.memory_delete(ns, "k")
    assert await backend.memory_search("titration", namespace=ns) == []
