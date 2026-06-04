from functools import wraps
from typing import Callable, Optional
from fastapi import Request, HTTPException, status
import logging

logger = logging.getLogger(__name__)


def rate_limit(
    limit: Optional[int] = None,
    period: Optional[int] = None,
    key_func: Optional[Callable[[Request], str]] = None,
):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if request is None:
                request = kwargs.get("request")
            
            if request is None:
                logger.warning("No request object found in rate_limit decorator")
                return await func(*args, **kwargs)
            
            limiter = request.app.state.limiter
            
            if key_func:
                identifier = key_func(request)
            else:
                client_ip = request.client.host if request.client else "unknown"
                identifier = f"ip:{client_ip}"
            
            try:
                result = await limiter.check_rate_limit(
                    identifier=identifier,
                    limit=limit,
                    period=period,
                )
                
                request.state.rate_limit_result = result
                
                if not result.allowed:
                    logger.warning(
                        f"Rate limit exceeded for {identifier}. "
                        f"Limit: {result.limit}, Retry after: {result.retry_after}s"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": "Rate limit exceeded",
                            "message": f"Too many requests. Please try again in {result.retry_after} seconds.",
                        },
                        headers={
                            "X-RateLimit-Limit": str(result.limit),
                            "X-RateLimit-Remaining": str(result.remaining),
                            "X-RateLimit-Reset": str(int(result.reset_at.timestamp())),
                            "Retry-After": str(result.retry_after),
                        },
                    )
                
                response = await func(*args, **kwargs)
                
                if hasattr(response, "headers"):
                    response.headers["X-RateLimit-Limit"] = str(result.limit)
                    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
                    response.headers["X-RateLimit-Reset"] = str(int(result.reset_at.timestamp()))
                
                return response
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Rate limiter error: {str(e)}", exc_info=True)
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def user_rate_limit(
    limit: Optional[int] = None,
    period: Optional[int] = None,
):
    def key_func(request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
    
    return rate_limit(limit=limit, period=period, key_func=key_func)


def endpoint_rate_limit(
    limit: Optional[int] = None,
    period: Optional[int] = None,
):
    def key_func(request: Request) -> str:
        client_ip = request.client.host if request.client else "unknown"
        endpoint = request.url.path
        return f"endpoint:{endpoint}:ip:{client_ip}"
    
    return rate_limit(limit=limit, period=period, key_func=key_func)
