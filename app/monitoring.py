from prometheus_client import Counter, Histogram, Gauge
import time
import logging
from typing import Optional
from app.rate_limiter.base import RateLimitResult

logger = logging.getLogger(__name__)

rate_limit_requests_total = Counter(
    "rate_limit_requests_total",
    "Total number of rate limit checks",
    ["identifier_type", "allowed"]
)

rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Total number of rate limit exceeded events",
    ["identifier_type"]
)

rate_limit_check_duration = Histogram(
    "rate_limit_check_duration_seconds",
    "Time spent checking rate limits",
    ["strategy"]
)

rate_limit_remaining_tokens = Gauge(
    "rate_limit_remaining_tokens",
    "Remaining tokens for rate limited identifiers",
    ["identifier"]
)


class RateLimitMonitor:
    @staticmethod
    def record_check(
        identifier: str,
        result: RateLimitResult,
        duration: float,
        strategy: str = "unknown"
    ):
        logger.info(f"[monitoring/RateLimitMonitor.record_check] invoked | identifier={identifier} strategy={strategy} duration={duration:.6f}")
        identifier_type = identifier.split(":")[0] if ":" in identifier else "unknown"
        
        rate_limit_requests_total.labels(
            identifier_type=identifier_type,
            allowed=str(result.allowed)
        ).inc()
        
        if not result.allowed:
            rate_limit_exceeded_total.labels(
                identifier_type=identifier_type
            ).inc()
        
        rate_limit_check_duration.labels(strategy=strategy).observe(duration)
        
        rate_limit_remaining_tokens.labels(identifier=identifier).set(result.remaining)
    
    @staticmethod
    def get_metrics() -> dict:
        logger.info("[monitoring/RateLimitMonitor.get_metrics] invoked")
        return {
            "rate_limit_requests_total": rate_limit_requests_total._value.get(),
            "rate_limit_exceeded_total": rate_limit_exceeded_total._value.get(),
        }
