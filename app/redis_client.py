import logging
import redis.asyncio as redis
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[redis.ConnectionPool] = None


def _build_url() -> str:
    if settings.redis_password:
        return f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
    return f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"


def init_pool() -> redis.ConnectionPool:
    global _pool
    logger.info("[redis_client/init_pool] invoked")
    connection_kwargs = {
        "encoding": "utf-8",
        "decode_responses": True,
    }
    if settings.redis_ssl:
        import ssl as ssl_module
        connection_kwargs["ssl_cert_reqs"] = ssl_module.CERT_REQUIRED

    logger.info("[redis_client/init_pool] -> ConnectionPool.from_url (establishing shared pool)")
    _pool = redis.ConnectionPool.from_url(_build_url(), **connection_kwargs)
    return _pool


def get_client() -> redis.Redis:
    logger.info("[redis_client/get_client] invoked")
    if _pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_pool() during startup.")
    return redis.Redis(connection_pool=_pool)


async def close_pool() -> None:
    global _pool
    logger.info("[redis_client/close_pool] invoked")
    if _pool is not None:
        logger.info("[redis_client/close_pool] -> pool.disconnect")
        await _pool.disconnect()
        _pool = None
