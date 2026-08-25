"""Temporary cache dump for Choreo testing. Hidden unless CACHE_DEBUG=true."""

from fastapi import APIRouter, HTTPException, Query

from src.cache import app_cache as app_cache_mod
from src.cache.redis_cache import RedisCache
from src.core import settings

router = APIRouter(tags=["Debug"])


@router.get("/debug/cache", include_in_schema=False)
async def dump_cache(
    match: str = Query(
        default="gi:*",
        description="Redis SCAN match pattern",
    ),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not settings.CACHE_DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    if not isinstance(app_cache_mod.cache, RedisCache):
        raise HTTPException(
            status_code=503,
            detail="Redis cache is not enabled (CACHE_ENABLED/REDIS_URL)",
        )
    result = await app_cache_mod.cache.debug_scan(match=match, limit=limit)
    if result.get("error") and not result["entries"]:
        raise HTTPException(status_code=503, detail=result["error"])
    return result
