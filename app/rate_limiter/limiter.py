import logging
import redis.asyncio as redis
from typing import Optional, Callable
from enum import Enum
from app.rate_limiter.base import RateLimiterStrategy, RateLimitResult
from app.rate_limiter.strategies import (
    FixedWindowStrategy,
    SlidingWindowStrategy,
    TokenBucketStrategy,
)
from app.config import settings

logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"


class RateLimiter:
    def __init__(
        self,
        redis_client: redis.Redis,
        strategy_type: StrategyType = StrategyType.SLIDING_WINDOW,
    ):
        logger.info(f"[limiter/RateLimiter.__init__] invoked | strategy_type={strategy_type}")
        self.redis_client = redis_client
        self.strategy_type = strategy_type
        self.strategy = self._build_strategy(strategy_type, redis_client)
    
    @staticmethod
    def _build_strategy(
        strategy_type: StrategyType,
        redis_client: redis.Redis,
    ) -> RateLimiterStrategy:
        logger.info(f"[limiter/RateLimiter._build_strategy] invoked | strategy_type={strategy_type}")
        if strategy_type == StrategyType.FIXED_WINDOW:
            return FixedWindowStrategy(redis_client)
        elif strategy_type == StrategyType.SLIDING_WINDOW:
            return SlidingWindowStrategy(redis_client)
        elif strategy_type == StrategyType.TOKEN_BUCKET:
            return TokenBucketStrategy(redis_client)
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    
    async def check_rate_limit(
        self,
        identifier: str,
        limit: Optional[int] = None,
        period: Optional[int] = None,
    ) -> RateLimitResult:
        logger.info(f"[limiter/RateLimiter.check_rate_limit] invoked | identifier={identifier} limit={limit} period={period}")
        if not settings.rate_limit_enabled:
            from datetime import datetime, timedelta
            return RateLimitResult(
                allowed=True,
                limit=limit or settings.default_rate_limit,
                remaining=limit or settings.default_rate_limit,
                reset_at=datetime.now() + timedelta(seconds=period or settings.default_rate_limit_period),
                retry_after=0
            )
        
        limit = limit or settings.default_rate_limit
        period = period or settings.default_rate_limit_period
        
        logger.info(f"[limiter/RateLimiter.check_rate_limit] -> strategy.is_allowed | strategy={self.strategy_type}")
        return await self.strategy.is_allowed(identifier, limit, period)
    
    async def reset_limit(self, identifier: str) -> None:
        logger.info(f"[limiter/RateLimiter.reset_limit] invoked | identifier={identifier}")
        logger.info("[limiter/RateLimiter.reset_limit] -> strategy.reset")
        await self.strategy.reset(identifier)
    
    def get_identifier(
        self,
        key_func: Optional[Callable] = None,
        **kwargs
    ) -> str:
        logger.info("[limiter/RateLimiter.get_identifier] invoked")
        if key_func:
            return key_func(**kwargs)
        
        parts = []
        for key, value in sorted(kwargs.items()):
            if value is not None:
                parts.append(f"{key}:{value}")
        
        return ":".join(parts) if parts else "global"
