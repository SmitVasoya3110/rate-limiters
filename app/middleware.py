from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Pure enforcement layer. It owns no rules: it asks the request-scoped
    ``app.state.rule_resolver`` for a decision and enforces it. Swap the
    resolver (static, Redis/DB-backed, per-subscription, ...) without touching
    this class."""

    def __init__(self, app):
        logger.info("[middleware/RateLimitMiddleware.__init__] invoked")
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next):
        logger.info(f"[middleware/RateLimitMiddleware.dispatch] invoked | method={request.method} path={request.url.path}")
        resolver = request.app.state.rule_resolver
        logger.info("[middleware/RateLimitMiddleware.dispatch] -> rule_resolver.resolve")
        decision = await resolver.resolve(request)
        if decision is None:
            logger.info(f"[middleware/RateLimitMiddleware.dispatch] no rule, skipping rate limit | path={request.url.path}")
            return await call_next(request)
        
        limiter = request.app.state.limiter
        logger.info("[middleware/RateLimitMiddleware.dispatch] -> limiter.check_rate_limit")
        
        try:
            result = await limiter.check_rate_limit(
                identifier=decision.identifier,
                limit=decision.limit,
                period=decision.period,
            )
            
            response = await call_next(request) if result.allowed else JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Please try again in {result.retry_after} seconds.",
                },
            )
            
            response.headers["X-RateLimit-Limit"] = str(result.limit)
            response.headers["X-RateLimit-Remaining"] = str(result.remaining)
            response.headers["X-RateLimit-Reset"] = str(int(result.reset_at.timestamp()))
            
            if not result.allowed:
                response.headers["Retry-After"] = str(result.retry_after)
                logger.warning(
                    f"Rate limit exceeded for {decision.identifier}. "
                    f"Limit: {result.limit}, Retry after: {result.retry_after}s"
                )
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limiter error: {str(e)}", exc_info=True)
            return await call_next(request)
