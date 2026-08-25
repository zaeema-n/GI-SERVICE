"""CACHE_DEBUG dump: hidden by default; Redis SCAN payload when enabled."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.cache.redis_cache import RedisCache


@pytest.mark.asyncio
async def test_debug_scan_disconnected_reports_error():
    cache = RedisCache("redis://localhost:6379/0")
    result = await cache.debug_scan(match="gi:*", limit=50)
    assert result["count"] == 0
    assert result["entries"] == []
    assert "not connected" in result["error"]


@pytest.mark.asyncio
async def test_debug_scan_returns_json_values_and_raw_locks():
    cache = RedisCache("redis://localhost:6379/0")
    cache._client = AsyncMock()

    async def scan_iter(*, match, count):
        assert match == "gi:*"
        for key in ("gi:v1:entity:1", "gi:lock:x"):
            yield key

    cache._client.scan_iter = scan_iter
    cache._client.ttl = AsyncMock(side_effect=[100, 5])
    cache._client.get = AsyncMock(side_effect=['{"id": "1"}', "token-abc"])

    result = await cache.debug_scan(match="gi:*", limit=50)
    assert result["count"] == 2
    assert result["truncated"] is False
    assert result["entries"][0] == {
        "key": "gi:v1:entity:1",
        "ttl_seconds": 100,
        "value": {"id": "1"},
    }
    assert result["entries"][1] == {
        "key": "gi:lock:x",
        "ttl_seconds": 5,
        "value": "token-abc",
    }


@pytest.mark.asyncio
async def test_debug_scan_truncates_large_values_and_respects_limit():
    cache = RedisCache("redis://localhost:6379/0")
    cache._client = AsyncMock()

    async def scan_iter(*, match, count):
        for key in ("a", "b", "c"):
            yield key

    cache._client.scan_iter = scan_iter
    cache._client.ttl = AsyncMock(return_value=10)
    cache._client.get = AsyncMock(return_value="x" * 50)

    result = await cache.debug_scan(match="gi:*", limit=2, max_value_chars=10)
    assert result["count"] == 2
    assert result["truncated"] is True
    assert result["entries"][0]["value"] == "x" * 10
    assert result["entries"][0]["value_truncated"] is True
    assert result["entries"][0]["value_chars"] == 50


def test_debug_cache_endpoint_hidden_when_flag_off():
    from main import app

    with TestClient(app) as client:
        response = client.get("/debug/cache")
    assert response.status_code == 404


def test_debug_cache_endpoint_dumps_when_flag_on():
    from main import app
    from src.cache import app_cache as app_cache_mod
    from src.core import settings

    redis = RedisCache("redis://unused")
    redis._client = AsyncMock()
    redis.debug_scan = AsyncMock(
        return_value={
            "count": 1,
            "truncated": False,
            "entries": [
                {"key": "gi:v1:entity:1", "ttl_seconds": 9, "value": {"ok": True}}
            ],
        }
    )

    with (
        patch.object(settings, "CACHE_DEBUG", True),
        patch.object(app_cache_mod, "cache", redis),
        TestClient(app) as client,
    ):
        response = client.get("/debug/cache")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["entries"][0]["key"] == "gi:v1:entity:1"
    redis.debug_scan.assert_awaited_once()
