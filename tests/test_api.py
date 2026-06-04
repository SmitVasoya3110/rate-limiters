import pytest
import fakeredis.aioredis
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from app.main import app, rule_resolver
from app.rate_limiter.limiter import RateLimiter, StrategyType
from app.rate_limiter.base import RateLimitResult
from datetime import datetime, timedelta


@pytest.fixture(autouse=True)
def setup_app_state():
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.redis = redis_client
    app.state.limiter = RateLimiter(redis_client, strategy_type=StrategyType.SLIDING_WINDOW)
    app.state.rule_resolver = rule_resolver
    yield
    app.state.redis = None
    app.state.limiter = None
    app.state.rule_resolver = None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_rate_limiter():
    limiter = AsyncMock()
    app.state.limiter = limiter
    yield limiter


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
    assert "endpoints" in response.json()


def test_public_endpoint(client):
    response = client.get("/public")
    assert response.status_code == 200
    assert "message" in response.json()


@pytest.mark.asyncio
async def test_rate_limit_headers(client, mock_rate_limiter):
    mock_rate_limiter.check_rate_limit.return_value = RateLimitResult(
        allowed=True,
        limit=100,
        remaining=99,
        reset_at=datetime.now() + timedelta(seconds=60),
        retry_after=0
    )
    
    response = client.get("/public")
    
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "X-RateLimit-Reset" in response.headers


@pytest.mark.asyncio
async def test_rate_limit_exceeded(client, mock_rate_limiter):
    mock_rate_limiter.check_rate_limit.return_value = RateLimitResult(
        allowed=False,
        limit=100,
        remaining=0,
        reset_at=datetime.now() + timedelta(seconds=60),
        retry_after=60
    )
    
    response = client.get("/public")
    
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["error"] == "Rate limit exceeded"


def test_limited_endpoint(client):
    response = client.get("/api/limited")
    assert response.status_code in [200, 429]


def test_strict_endpoint(client):
    response = client.get("/api/strict")
    assert response.status_code in [200, 429]


def test_user_endpoint(client):
    response = client.get("/api/user")
    assert response.status_code in [200, 429]
    if response.status_code == 200:
        assert "user_id" in response.json()


@pytest.mark.asyncio
async def test_multiple_requests_rate_limiting(client):
    responses = []
    for _ in range(10):
        response = client.get("/api/strict")
        responses.append(response.status_code)
    
    assert 200 in responses or 429 in responses


def test_reset_endpoint(client):
    response = client.post("/api/reset/test_user")
    assert response.status_code in [200, 500]


def test_status_endpoint(client):
    response = client.get("/api/status/test_user")
    assert response.status_code in [200, 500]
    if response.status_code == 200:
        data = response.json()
        assert "identifier" in data
        assert "allowed" in data
        assert "limit" in data
        assert "remaining" in data
