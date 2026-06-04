# Production-Ready API Rate Limiter with FastAPI

A comprehensive, production-ready API rate limiting solution built with FastAPI and Redis, implementing multiple rate limiting strategies.

## Features

- **Multiple Rate Limiting Strategies**
  - Fixed Window: Simple counter-based rate limiting
  - Sliding Window: More accurate time-based rate limiting
  - Token Bucket: Smooth rate limiting with burst support

- **Production-Ready Components**
  - Redis-backed persistence
  - FastAPI middleware integration
  - Decorator-based rate limiting
  - Prometheus metrics integration
  - Comprehensive error handling
  - Configurable via environment variables

- **Flexible Configuration**
  - Per-IP rate limiting
  - Per-user rate limiting
  - Per-endpoint rate limiting
  - Custom identifier functions
  - Dynamic limit configuration

## Architecture

### Rate Limiting Strategies

#### 1. Fixed Window
- Divides time into fixed windows (e.g., 1 minute)
- Counts requests within each window
- Simple and efficient
- May allow burst at window boundaries

#### 2. Sliding Window
- Uses a rolling time window
- More accurate than fixed window
- Prevents burst at boundaries
- Slightly more complex

#### 3. Token Bucket
- Tokens refill at a constant rate
- Allows controlled bursts
- Smooth rate limiting
- Best for APIs with variable load

## Installation

1. Clone the repository:
```bash
cd /home/smit/concepts/api-rate-limiter
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up Redis:
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or install Redis locally
# Ubuntu/Debian
sudo apt-get install redis-server

# macOS
brew install redis
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your configuration
```

## Configuration

Edit `.env` file:

```env
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_SSL=false

RATE_LIMIT_ENABLED=true
DEFAULT_RATE_LIMIT=100
DEFAULT_RATE_LIMIT_PERIOD=60

ENVIRONMENT=development
LOG_LEVEL=INFO
```

## Usage

### Running the Application

```bash
# Development mode with auto-reload
python -m app.main

# Or using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Using Middleware (Global Rate Limiting)

```python
from fastapi import FastAPI
from app.middleware import RateLimitMiddleware

app = FastAPI()

app.add_middleware(
    RateLimitMiddleware,
    limit=100,
    period=60,
    key_func=lambda request: f"ip:{request.client.host}"
)
```

### Using Decorators (Per-Endpoint Rate Limiting)

```python
from fastapi import FastAPI, Request
from app.decorators import rate_limit, user_rate_limit, endpoint_rate_limit

app = FastAPI()

@app.get("/api/limited")
@rate_limit(limit=10, period=60)
async def limited_endpoint(request: Request):
    return {"message": "Rate limited endpoint"}

@app.get("/api/user")
@user_rate_limit(limit=50, period=60)
async def user_endpoint(request: Request):
    return {"message": "User-specific rate limiting"}

@app.get("/api/strict")
@endpoint_rate_limit(limit=5, period=60)
async def strict_endpoint(request: Request):
    return {"message": "Strict rate limiting"}
```

### Custom Rate Limiter

```python
from app.rate_limiter import RateLimiter, StrategyType

# Initialize with specific strategy
limiter = RateLimiter(strategy_type=StrategyType.SLIDING_WINDOW)
await limiter.connect()

# Check rate limit
result = await limiter.check_rate_limit(
    identifier="user:123",
    limit=100,
    period=60
)

if result.allowed:
    print(f"Request allowed. Remaining: {result.remaining}")
else:
    print(f"Rate limit exceeded. Retry after: {result.retry_after}s")

# Reset rate limit
await limiter.reset_limit("user:123")

await limiter.disconnect()
```

## API Endpoints

### Available Endpoints

- `GET /` - API information and available endpoints
- `GET /health` - Health check endpoint
- `GET /metrics` - Prometheus metrics
- `GET /public` - Public endpoint with global rate limit
- `GET /api/limited` - Limited endpoint (10 req/min)
- `GET /api/user` - User-specific rate limit (50 req/min)
- `GET /api/strict` - Strict rate limit (5 req/min)
- `POST /api/reset/{identifier}` - Reset rate limit for identifier
- `GET /api/status/{identifier}` - Check rate limit status

### Response Headers

All rate-limited responses include:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Unix timestamp when limit resets
- `Retry-After`: Seconds to wait before retry (when rate limited)

### Example Response (Rate Limited)

```json
{
  "error": "Rate limit exceeded",
  "message": "Too many requests. Please try again in 45 seconds."
}
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_strategies.py

# Run with verbose output
pytest -v
```

## Monitoring

### Prometheus Metrics

Access metrics at `/metrics`:

- `rate_limit_requests_total`: Total rate limit checks
- `rate_limit_exceeded_total`: Total rate limit exceeded events
- `rate_limit_check_duration_seconds`: Time spent checking rate limits
- `rate_limit_remaining_tokens`: Remaining tokens per identifier

### Example Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'api-rate-limiter'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

## Performance Considerations

### Strategy Comparison

| Strategy | Accuracy | Performance | Memory | Burst Handling |
|----------|----------|-------------|---------|----------------|
| Fixed Window | Low | High | Low | Poor |
| Sliding Window | High | Medium | Medium | Good |
| Token Bucket | High | Medium | Low | Excellent |

### Recommendations

- **Fixed Window**: High-throughput APIs, less strict requirements
- **Sliding Window**: General purpose, balanced accuracy/performance
- **Token Bucket**: APIs requiring burst support, variable load

## Production Deployment

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    depends_on:
      - redis
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### Environment Variables for Production

```env
REDIS_HOST=redis-production.example.com
REDIS_PORT=6379
REDIS_PASSWORD=your-secure-password
REDIS_SSL=true

RATE_LIMIT_ENABLED=true
DEFAULT_RATE_LIMIT=1000
DEFAULT_RATE_LIMIT_PERIOD=60

ENVIRONMENT=production
LOG_LEVEL=WARNING
```

## Best Practices

1. **Choose the Right Strategy**
   - Use Fixed Window for simple use cases
   - Use Sliding Window for better accuracy
   - Use Token Bucket for burst handling

2. **Set Appropriate Limits**
   - Consider your infrastructure capacity
   - Monitor actual usage patterns
   - Adjust limits based on metrics

3. **Handle Rate Limit Errors**
   - Return clear error messages
   - Include Retry-After header
   - Log rate limit events

4. **Monitor and Alert**
   - Track rate limit metrics
   - Set up alerts for unusual patterns
   - Review logs regularly

5. **Security Considerations**
   - Use Redis password in production
   - Enable SSL for Redis connections
   - Implement IP whitelisting if needed
   - Consider DDoS protection

## Troubleshooting

### Redis Connection Issues

```bash
# Check Redis is running
redis-cli ping

# Check Redis connection
redis-cli -h localhost -p 6379 ping
```

### Rate Limit Not Working

1. Check Redis connection in `/health` endpoint
2. Verify `RATE_LIMIT_ENABLED=true` in `.env`
3. Check logs for errors
4. Verify Redis keys: `redis-cli KEYS "rate_limit:*"`

### Performance Issues

1. Monitor Redis memory usage
2. Check rate limiter strategy
3. Review concurrent request patterns
4. Consider Redis clustering for high load

## Advanced Usage

### Custom Identifier Function

```python
def custom_identifier(request: Request) -> str:
    # Combine multiple factors
    user_id = getattr(request.state, "user_id", None)
    api_key = request.headers.get("X-API-Key")
    
    if user_id:
        return f"user:{user_id}"
    elif api_key:
        return f"api_key:{api_key}"
    else:
        return f"ip:{request.client.host}"

app.add_middleware(
    RateLimitMiddleware,
    key_func=custom_identifier
)
```

### Multiple Rate Limits

```python
@app.get("/api/complex")
@rate_limit(limit=100, period=60)  # 100 per minute
@rate_limit(limit=1000, period=3600)  # 1000 per hour
async def complex_endpoint(request: Request):
    return {"message": "Multiple rate limits"}
```

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Write tests for new features
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - feel free to use in your projects.

## Support

For issues and questions:
- Check the troubleshooting section
- Review test files for examples
- Open an issue on GitHub

## Roadmap

- [ ] Distributed rate limiting across multiple instances
- [ ] Rate limit analytics dashboard
- [ ] GraphQL support
- [ ] WebSocket rate limiting
- [ ] Advanced burst algorithms
- [ ] Rate limit templates
