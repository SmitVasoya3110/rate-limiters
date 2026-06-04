import time
import logging
from datetime import datetime, timedelta
from typing import Optional
import redis.asyncio as redis
from app.rate_limiter.base import RateLimiterStrategy, RateLimitResult

logger = logging.getLogger(__name__)


class FixedWindowStrategy(RateLimiterStrategy):
    def __init__(self, redis_client: redis.Redis):
        logger.info("[strategies/FixedWindowStrategy.__init__] invoked")
        self.redis = redis_client
    
    async def is_allowed(self, key: str, limit: int, period: int) -> RateLimitResult:
        logger.info(f"[strategies/FixedWindowStrategy.is_allowed] invoked | key={key} limit={limit} period={period}")
        current_window = int(time.time() / period)
        window_key = f"rate_limit:fixed:{key}:{current_window}"
        
        pipe = self.redis.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, period * 2)
        logger.info(f"[strategies/FixedWindowStrategy.is_allowed] -> redis.pipeline.execute (INCR, EXPIRE) | window_key={window_key}")
        results = await pipe.execute()
        
        current_count = results[0]
        allowed = current_count <= limit
        remaining = max(0, limit - current_count)
        
        reset_at = datetime.fromtimestamp((current_window + 1) * period)
        retry_after = int((reset_at - datetime.now()).total_seconds()) if not allowed else 0
        
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after
        )
    
    async def reset(self, key: str) -> None:
        logger.info(f"[strategies/FixedWindowStrategy.reset] invoked | key={key}")
        pattern = f"rate_limit:fixed:{key}:*"
        cursor = 0
        while True:
            logger.info(f"[strategies/FixedWindowStrategy.reset] -> redis.scan | pattern={pattern} cursor={cursor}")
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                logger.info(f"[strategies/FixedWindowStrategy.reset] -> redis.delete | keys={keys}")
                await self.redis.delete(*keys)
            if cursor == 0:
                break


class SlidingWindowStrategy(RateLimiterStrategy):
    def __init__(self, redis_client: redis.Redis):
        logger.info("[strategies/SlidingWindowStrategy.__init__] invoked")
        self.redis = redis_client
    
    async def is_allowed(self, key: str, limit: int, period: int) -> RateLimitResult:
        logger.info(f"[strategies/SlidingWindowStrategy.is_allowed] invoked | key={key} limit={limit} period={period}")
        now = time.time()
        window_key = f"rate_limit:sliding:{key}"
        

        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local period = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        
        redis.call('ZREMRANGEBYSCORE', key, 0, now - period)
        local count = redis.call('ZCARD', key)
        
        local allowed = 0
        if count < limit then
            redis.call('ZADD', key, now, tostring(now))
            redis.call('EXPIRE', key, period)
            allowed = 1
        end
        
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        local oldest_timestamp = now
        if #oldest > 0 then
            oldest_timestamp = tonumber(oldest[2])
        end
        
        return {allowed, count, oldest_timestamp}
        """
        
        logger.info(f"[strategies/SlidingWindowStrategy.is_allowed] -> redis.eval (sliding-window Lua: ZREMRANGEBYSCORE, ZCARD, ZADD, EXPIRE, ZRANGE) | window_key={window_key}")
        result = await self.redis.eval(
            lua_script,
            1,
            window_key,
            now,
            period,
            limit
        )
        
        allowed = bool(result[0])
        current_count = int(result[1])
        oldest_timestamp = float(result[2])
        
        remaining = max(0, limit - current_count - (1 if allowed else 0))
        reset_at = datetime.fromtimestamp(oldest_timestamp + period)
        retry_after = int((reset_at - datetime.now()).total_seconds()) if not allowed else 0
        
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after
        )
    
    async def reset(self, key: str) -> None:
        logger.info(f"[strategies/SlidingWindowStrategy.reset] invoked | key={key}")
        window_key = f"rate_limit:sliding:{key}"
        logger.info(f"[strategies/SlidingWindowStrategy.reset] -> redis.delete | window_key={window_key}")
        await self.redis.delete(window_key)


class TokenBucketStrategy(RateLimiterStrategy):
    def __init__(self, redis_client: redis.Redis):
        logger.info("[strategies/TokenBucketStrategy.__init__] invoked")
        self.redis = redis_client
    
    async def is_allowed(self, key: str, limit: int, period: int) -> RateLimitResult:
        logger.info(f"[strategies/TokenBucketStrategy.is_allowed] invoked | key={key} limit={limit} period={period}")
        now = time.time()
        bucket_key = f"rate_limit:token:{key}"
        
        lua_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local period = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local rate = limit / period
        
        local bucket = redis.call('HMGET', key, 'tokens', 'last_update')
        local tokens = tonumber(bucket[1])
        local last_update = tonumber(bucket[2])
        
        if tokens == nil then
            tokens = limit
            last_update = now
        else
            local elapsed = now - last_update
            tokens = math.min(limit, tokens + (elapsed * rate))
            last_update = now
        end
        
        local allowed = 0
        if tokens >= 1 then
            tokens = tokens - 1
            allowed = 1
        end
        
        redis.call('HMSET', key, 'tokens', tokens, 'last_update', last_update)
        redis.call('EXPIRE', key, period * 2)
        
        return {allowed, math.floor(tokens), last_update}
        """
        
        logger.info(f"[strategies/TokenBucketStrategy.is_allowed] -> redis.eval (token-bucket Lua: HMGET, HMSET, EXPIRE) | bucket_key={bucket_key}")
        result = await self.redis.eval(
            lua_script,
            1,
            bucket_key,
            limit,
            period,
            now
        )
        
        allowed = bool(result[0])
        remaining = int(result[1])
        last_update = float(result[2])
        
        tokens_needed = 1 - (remaining / limit) * limit
        time_to_refill = tokens_needed / (limit / period)
        reset_at = datetime.fromtimestamp(last_update + time_to_refill)
        retry_after = int(time_to_refill) if not allowed else 0
        
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after
        )
    
    async def reset(self, key: str) -> None:
        logger.info(f"[strategies/TokenBucketStrategy.reset] invoked | key={key}")
        bucket_key = f"rate_limit:token:{key}"
        logger.info(f"[strategies/TokenBucketStrategy.reset] -> redis.delete | bucket_key={bucket_key}")
        await self.redis.delete(bucket_key)
