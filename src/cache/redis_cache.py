"""Redis-backed cache using redis.asyncio (connect/close wired via app lifespan).

Redis is best-effort: get/set/delete failures are logged and swallowed so the
API can keep serving from OpenGIN (fail-open).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.connection import BlockingConnectionPool
from redis.exceptions import RedisError
from src.core import settings

logger = logging.getLogger(__name__)

# Connection / protocol failures we treat as "cache unavailable"
_REDIS_SOFT_ERRORS = (RedisError, ConnectionError, OSError, TimeoutError)


def _decode_debug_value(raw: str | None, max_chars: int) -> tuple[Any, bool]:
    if raw is None:
        return None, False
    if len(raw) > max_chars:
        return raw[:max_chars], True
    try:
        return json.loads(raw), False
    except (json.JSONDecodeError, TypeError):
        return raw, False


class RedisCache:
    """Redis implementation of CacheBackend. Call connect() before get/set/delete."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        """Expose the async client for SingleFlight Redis locks."""
        if self._client is None:
            raise RuntimeError(
                "Redis cache not initialized; call connect() in lifespan"
            )
        return self._client

    async def connect(self) -> None:
        if self._client is None:
            # Use a blocking pool so short Redis bursts wait briefly for a free
            # connection instead of immediately fail-opening on pool exhaustion.
            pool = BlockingConnectionPool.from_url(
                self._redis_url,
                decode_responses=True,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                timeout=settings.REDIS_POOL_TIMEOUT_SECONDS,
            )
            self._client = Redis(connection_pool=pool)
            await self._client.ping()
            logger.info("Redis cache connected")

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except _REDIS_SOFT_ERRORS as exc:
                logger.warning("Redis close failed: %s", exc)
            self._client = None
            logger.info("Redis cache closed")

    async def get(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Redis get bad payload key=%s: %s", key, exc)
            return None
        except _REDIS_SOFT_ERRORS as exc:
            logger.warning("Redis get failed key=%s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if self._client is None:
            return
        try:
            if ttl_seconds <= 0:
                await self.delete(key)
                return
            await self._client.set(key, json.dumps(value), ex=ttl_seconds)
        except (TypeError, ValueError) as exc:
            logger.warning("Redis set encode failed key=%s: %s", key, exc)
        except _REDIS_SOFT_ERRORS as exc:
            logger.warning("Redis set failed key=%s: %s", key, exc)

    async def delete(self, key: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.delete(key)
        except _REDIS_SOFT_ERRORS as exc:
            logger.warning("Redis delete failed key=%s: %s", key, exc)

    async def debug_scan(
        self,
        *,
        match: str,
        limit: int,
        max_value_chars: int = 8_000,
    ) -> dict[str, Any]:
        """List keys currently in Redis (for CACHE_DEBUG dumps only)."""
        empty: dict[str, Any] = {"count": 0, "truncated": False, "entries": []}
        if self._client is None:
            return {**empty, "error": "Redis client not connected"}
        entries: list[dict[str, Any]] = []
        truncated = False
        try:
            async for key in self._client.scan_iter(match=match, count=100):
                if len(entries) >= limit:
                    truncated = True
                    break
                ttl = await self._client.ttl(key)
                raw = await self._client.get(key)
                value, value_truncated = _decode_debug_value(raw, max_value_chars)
                entry: dict[str, Any] = {
                    "key": key,
                    "ttl_seconds": ttl,
                    "value": value,
                }
                if value_truncated:
                    entry["value_truncated"] = True
                    entry["value_chars"] = len(raw) if raw is not None else 0
                entries.append(entry)
        except _REDIS_SOFT_ERRORS as exc:
            logger.warning("Redis debug_scan failed: %s", exc)
            return {**empty, "error": str(exc)}
        return {"count": len(entries), "truncated": truncated, "entries": entries}
