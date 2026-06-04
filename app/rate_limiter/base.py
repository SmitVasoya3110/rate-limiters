from abc import ABC, abstractmethod
from typing import Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after: int = 0


class RateLimiterStrategy(ABC):
    @abstractmethod
    async def is_allowed(self, key: str, limit: int, period: int) -> RateLimitResult:
        pass
    
    @abstractmethod
    async def reset(self, key: str) -> None:
        pass
