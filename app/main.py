from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.rate_limiter.limiter import RateLimiter, StrategyType
from app.redis_client import init_pool, get_client, close_pool
from app.middleware import RateLimitMiddleware
from app.rules import StaticRuleResolver, RateLimitRule, ChainResolver, RedisOverrideResolver
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    logger.info("[main/get_client_identifier] invoked")
    return f"ip:{request.client.host}" if request.client else "ip:unknown"


def user_key(request: Request) -> str:
    logger.info("[main/user_key] invoked")
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_client_identifier(request)


def endpoint_ip_key(request: Request) -> str:
    logger.info("[main/endpoint_ip_key] invoked")
    return f"endpoint:{request.url.path}:{get_client_identifier(request)}"


rule_resolver = ChainResolver([
    # Dynamic, per-subscription overrides (evolve limits via Redis, no deploy).
    # Defers when no override exists, so the static rules below apply.
    RedisOverrideResolver(default_key_func=get_client_identifier),
    # Terminal: static path rules + defaults (never defers).
    StaticRuleResolver(
        default_limit=100,
        default_period=60,
        default_key_func=get_client_identifier,
        excluded_paths=["/", "/health", "/metrics"],
        path_rules={
            "/api/limited": RateLimitRule(limit=10, period=60),
            "/api/user": RateLimitRule(limit=50, period=60, key_func=user_key),
            "/api/strict": RateLimitRule(limit=5, period=60, key_func=endpoint_ip_key),
        },
    ),
])


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[main/lifespan] invoked")
    logger.info("Starting up application...")
    init_pool()
    app.state.redis = get_client()
    app.state.limiter = RateLimiter(app.state.redis, strategy_type=StrategyType.SLIDING_WINDOW)
    app.state.rule_resolver = rule_resolver
    logger.info(f"Rate limiter ready with strategy: {app.state.limiter.strategy_type}")
    yield
    logger.info("Shutting down application...")
    await close_pool()


def get_limiter(request: Request) -> RateLimiter:
    logger.info("[main/get_limiter] invoked")
    return request.app.state.limiter


app = FastAPI(
    title="API Rate Limiter Demo",
    description="Production-ready API rate limiter with multiple strategies",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    logger.info("[main/root] invoked")
    return {
        "message": "API Rate Limiter Demo",
        "endpoints": {
            "/public": "Public endpoint with global rate limit (100 req/min)",
            "/api/limited": "Limited endpoint (10 req/min per IP)",
            "/api/user": "User-specific rate limit (50 req/min per user)",
            "/api/strict": "Strict rate limit (5 req/min per IP)",
            "/health": "Health check endpoint",
            "/metrics": "Prometheus metrics endpoint",
        }
    }


@app.get("/health")
async def health_check(request: Request):
    logger.info("[main/health_check] invoked")
    try:
        logger.info("[main/health_check] -> redis.ping")
        await request.app.state.redis.ping()
        return {"status": "healthy", "redis": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/metrics")
async def metrics():
    logger.info("[main/metrics] invoked")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/public")
async def public_endpoint(request: Request):
    logger.info("[main/public_endpoint] invoked")
    return {
        "message": "This is a public endpoint with global rate limiting",
        "client_ip": request.client.host if request.client else "unknown"
    }


@app.get("/api/limited")
async def limited_endpoint(request: Request):
    logger.info("[main/limited_endpoint] invoked")
    return {
        "message": "This endpoint is rate limited to 10 requests per minute per IP",
        "client_ip": request.client.host if request.client else "unknown"
    }


@app.get("/api/user")
async def user_endpoint(request: Request):
    logger.info("[main/user_endpoint] invoked")
    user_id = getattr(request.state, "user_id", None)
    return {
        "message": "This endpoint is rate limited per user (50 req/min)",
        "user_id": user_id or "anonymous",
        "client_ip": request.client.host if request.client else "unknown"
    }


@app.get("/api/strict")
async def strict_endpoint(request: Request):
    logger.info("[main/strict_endpoint] invoked")
    return {
        "message": "This endpoint has strict rate limiting (5 req/min per IP)",
        "client_ip": request.client.host if request.client else "unknown"
    }


@app.post("/api/reset/{identifier}")
async def reset_rate_limit(identifier: str, limiter: RateLimiter = Depends(get_limiter)):
    logger.info(f"[main/reset_rate_limit] invoked | identifier={identifier}")
    try:
        await limiter.reset_limit(identifier)
        return {"message": f"Rate limit reset for {identifier}"}
    except Exception as e:
        logger.error(f"Failed to reset rate limit: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/status/{identifier}")
async def check_status(identifier: str, limiter: RateLimiter = Depends(get_limiter)):
    logger.info(f"[main/check_status] invoked | identifier={identifier}")
    try:
        result = await limiter.check_rate_limit(identifier, limit=100, period=60)
        return {
            "identifier": identifier,
            "allowed": result.allowed,
            "limit": result.limit,
            "remaining": result.remaining,
            "reset_at": result.reset_at.isoformat(),
            "retry_after": result.retry_after
        }
    except Exception as e:
        logger.error(f"Failed to check status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


app.add_middleware(RateLimitMiddleware)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower()
    )
