"""The read-retry decorator retries transient connection loss (a backend killed
under us surfaces as AdminShutdown) but lets other errors propagate immediately.

Pure unit test: no Postgres required, so it runs even without DATABASE_URL.
"""
from __future__ import annotations

import psycopg
import pytest

from storage.postgres import _retry_reads


class _Flaky:
    def __init__(self, errors):
        self._errors = list(errors)
        self.calls = 0

    @_retry_reads
    async def read(self):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return "ok"


async def test_retries_then_succeeds_on_admin_shutdown():
    obj = _Flaky([psycopg.errors.AdminShutdown()])
    assert await obj.read() == "ok"
    assert obj.calls == 2  # one failure + one success


async def test_non_retryable_propagates_immediately():
    obj = _Flaky([ValueError("nope")])
    with pytest.raises(ValueError):
        await obj.read()
    assert obj.calls == 1  # not retried


async def test_gives_up_after_exhausting_retries():
    obj = _Flaky([psycopg.errors.AdminShutdown()] * 5)
    with pytest.raises(psycopg.errors.AdminShutdown):
        await obj.read()
    assert obj.calls == 3  # _READ_RETRIES
