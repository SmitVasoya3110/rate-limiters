import pytest
import fakeredis.aioredis
from app.rate_limiter.limiter import RateLimiter, StrategyType
from app.rate_limiter.strategies import (
    FixedWindowStrategy,
    SlidingWindowStrategy,
    TokenBucketStrategy,
)


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.close()


@pytest.fixture
async def fixed_window_strategy(redis_client):
    return FixedWindowStrategy(redis_client)


@pytest.fixture
async def sliding_window_strategy(redis_client):
    return SlidingWindowStrategy(redis_client)


@pytest.fixture
async def token_bucket_strategy(redis_client):
    return TokenBucketStrategy(redis_client)


@pytest.fixture
async def rate_limiter_fixed(redis_client):
    return RateLimiter(redis_client, strategy_type=StrategyType.FIXED_WINDOW)


@pytest.fixture
async def rate_limiter_sliding(redis_client):
    return RateLimiter(redis_client, strategy_type=StrategyType.SLIDING_WINDOW)


@pytest.fixture
async def rate_limiter_token(redis_client):
    return RateLimiter(redis_client, strategy_type=StrategyType.TOKEN_BUCKET)
