import pytest
import asyncio
from datetime import datetime


@pytest.mark.asyncio
async def test_fixed_window_basic(fixed_window_strategy):
    key = "test_user"
    limit = 5
    period = 60
    
    for i in range(limit):
        result = await fixed_window_strategy.is_allowed(key, limit, period)
        assert result.allowed is True
        assert result.remaining == limit - i - 1
    
    result = await fixed_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is False
    assert result.remaining == 0


@pytest.mark.asyncio
async def test_fixed_window_reset(fixed_window_strategy):
    key = "test_user"
    limit = 3
    period = 60
    
    for _ in range(limit):
        await fixed_window_strategy.is_allowed(key, limit, period)
    
    result = await fixed_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is False
    
    await fixed_window_strategy.reset(key)
    
    result = await fixed_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_sliding_window_basic(sliding_window_strategy):
    key = "test_user"
    limit = 5
    period = 60
    
    for i in range(limit):
        result = await sliding_window_strategy.is_allowed(key, limit, period)
        assert result.allowed is True
        assert result.remaining >= 0
    
    result = await sliding_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is False


@pytest.mark.asyncio
async def test_sliding_window_time_decay(sliding_window_strategy):
    key = "test_user"
    limit = 3
    period = 2
    
    for _ in range(limit):
        await sliding_window_strategy.is_allowed(key, limit, period)
    
    result = await sliding_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is False
    
    await asyncio.sleep(2.1)
    
    result = await sliding_window_strategy.is_allowed(key, limit, period)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_token_bucket_basic(token_bucket_strategy):
    key = "test_user"
    limit = 5
    period = 60
    
    for i in range(limit):
        result = await token_bucket_strategy.is_allowed(key, limit, period)
        assert result.allowed is True
    
    result = await token_bucket_strategy.is_allowed(key, limit, period)
    assert result.allowed is False


@pytest.mark.asyncio
async def test_token_bucket_refill(token_bucket_strategy):
    key = "test_user"
    limit = 10
    period = 1
    
    for _ in range(limit):
        await token_bucket_strategy.is_allowed(key, limit, period)
    
    result = await token_bucket_strategy.is_allowed(key, limit, period)
    assert result.allowed is False
    
    await asyncio.sleep(0.2)
    
    result = await token_bucket_strategy.is_allowed(key, limit, period)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_multiple_users_isolation(fixed_window_strategy):
    user1 = "user1"
    user2 = "user2"
    limit = 3
    period = 60
    
    for _ in range(limit):
        result1 = await fixed_window_strategy.is_allowed(user1, limit, period)
        assert result1.allowed is True
    
    result1 = await fixed_window_strategy.is_allowed(user1, limit, period)
    assert result1.allowed is False
    
    result2 = await fixed_window_strategy.is_allowed(user2, limit, period)
    assert result2.allowed is True


@pytest.mark.asyncio
async def test_rate_limit_result_fields(sliding_window_strategy):
    key = "test_user"
    limit = 10
    period = 60
    
    result = await sliding_window_strategy.is_allowed(key, limit, period)
    
    assert isinstance(result.allowed, bool)
    assert isinstance(result.limit, int)
    assert isinstance(result.remaining, int)
    assert isinstance(result.reset_at, datetime)
    assert isinstance(result.retry_after, int)
    assert result.limit == limit
    assert result.remaining <= limit
