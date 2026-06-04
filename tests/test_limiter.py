import pytest
from app.rate_limiter.limiter import RateLimiter, StrategyType


@pytest.mark.asyncio
async def test_rate_limiter_check(rate_limiter_sliding):
    identifier = "test_user"
    limit = 10
    period = 60
    
    result = await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    
    assert result.allowed is True
    assert result.limit == limit
    assert result.remaining <= limit


@pytest.mark.asyncio
async def test_rate_limiter_multiple_checks(rate_limiter_sliding):
    identifier = "test_user"
    limit = 5
    period = 60
    
    for i in range(limit):
        result = await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
        assert result.allowed is True
    
    result = await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    assert result.allowed is False


@pytest.mark.asyncio
async def test_rate_limiter_reset(rate_limiter_sliding):
    identifier = "test_user"
    limit = 3
    period = 60
    
    for _ in range(limit):
        await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    
    result = await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    assert result.allowed is False
    
    await rate_limiter_sliding.reset_limit(identifier)
    
    result = await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_rate_limiter_get_identifier(rate_limiter_sliding):
    identifier = rate_limiter_sliding.get_identifier(ip="192.168.1.1", user="john")
    assert "ip:192.168.1.1" in identifier
    assert "user:john" in identifier


@pytest.mark.asyncio
async def test_rate_limiter_custom_key_func(rate_limiter_sliding):
    def custom_key(ip, user):
        return f"custom:{user}:{ip}"
    
    identifier = rate_limiter_sliding.get_identifier(
        key_func=custom_key,
        ip="192.168.1.1",
        user="john"
    )
    assert identifier == "custom:john:192.168.1.1"


@pytest.mark.asyncio
async def test_different_strategies(redis_client):
    strategies = [
        StrategyType.FIXED_WINDOW,
        StrategyType.SLIDING_WINDOW,
        StrategyType.TOKEN_BUCKET,
    ]
    
    for strategy in strategies:
        limiter = RateLimiter(redis_client, strategy_type=strategy)
        assert limiter.strategy_type == strategy


@pytest.mark.asyncio
async def test_rate_limiter_concurrent_requests(rate_limiter_sliding):
    import asyncio
    
    identifier = "test_user"
    limit = 10
    period = 60
    
    async def make_request():
        return await rate_limiter_sliding.check_rate_limit(identifier, limit, period)
    
    results = await asyncio.gather(*[make_request() for _ in range(15)])
    
    allowed_count = sum(1 for r in results if r.allowed)
    assert allowed_count <= limit
