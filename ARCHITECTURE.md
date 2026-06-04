# Architecture Documentation

## System Overview

The API Rate Limiter is built with a modular architecture that separates concerns and allows for easy extension and customization. Two design ideas dominate the current layout:

- **Policy vs. mechanism**: a swappable **Rule Resolver** decides *which* limit applies (or whether to bypass), while the middleware is a thin *enforcer* that knows nothing about rules.
- **Shared infrastructure assembled once**: the FastAPI `lifespan` creates a single Redis connection pool and the shared `RateLimiter` / resolver, exposing them on `app.state`.

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                          │
│   lifespan builds the shared pool, limiter & resolver on          │
│   app.state at startup; close_pool() on shutdown                  │
├─────────────────────────────────────────────────────────────────┤
│   HTTP request                                                    │
│        │                                                          │
│        ▼                                                          │
│  ┌──────────────┐   resolve()    ┌──────────────────────────┐     │
│  │  Middleware  │ ─────────────▶ │   Rule Resolver (chain)  │     │
│  │ (enforcer)   │ ◀── Outcome ── │  Redis override → Static │     │
│  └──────┬───────┘                └──────────────────────────┘     │
│         │ Limit (decision)                                        │
│         ▼                                                         │
│  ┌──────────────────────┐                                        │
│  │   Rate Limiter Core  │   (also reachable via @decorators)      │
│  └──────────┬───────────┘                                        │
│             ▼                                                     │
│      ┌─────────────┐                                              │
│      │  Strategies │                                              │
│      └──────┬──────┘                                              │
│             ▼                                                     │
│  ┌──────────────────────┐      ┌──────────────┐                  │
│  │ redis_client (pool)  │ ───▶ │     Redis    │                  │
│  └──────────────────────┘      └──────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

> See `docs/flow.html` for an interactive, clickable version of these flows
> (request lifecycle, resolver chain, call graph, strategies, and startup wiring).

## Core Components

### 0. Connection Management (`app/redis_client.py`)

Owns the **single shared Redis connection pool** for the whole process, keeping connection lifecycle out of the rate-limiting logic.

**Functions:**
- `init_pool()`: Build the shared `redis.asyncio.ConnectionPool` (honours `REDIS_SSL`). Called once at startup.
- `get_client()`: Return a `redis.Redis` bound to the shared pool.
- `close_pool()`: Disconnect the pool on shutdown.

The `RateLimiter` and resolvers receive a client; they never build or own connections.

### 1. Rate Limiter Core (`app/rate_limiter/limiter.py`)

The central component that orchestrates rate limiting operations. The Redis client is **injected** (no connection management here).

**Responsibilities:**
- Build and switch between strategies (`_build_strategy`)
- Provide a high-level API for rate limit checks
- Generate identifiers from request context

**Constructor:**
- `RateLimiter(redis_client, strategy_type=StrategyType.SLIDING_WINDOW)`

**Key Methods:**
- `check_rate_limit(identifier, limit=None, period=None)`: Check if a request is allowed
- `reset_limit(identifier)`: Reset the rate limit for an identifier
- `get_identifier(key_func=None, **kwargs)`: Generate a unique identifier

### 2. Strategy Pattern (`app/rate_limiter/strategies.py`)

Implements different rate limiting algorithms using the Strategy pattern.

#### Fixed Window Strategy

**Algorithm:**
```
1. Calculate current window: window = floor(current_time / period)
2. Increment counter for window
3. Check if counter <= limit
4. Set expiration on key
```

**Pros:**
- Simple and fast
- Low memory usage
- Easy to understand

**Cons:**
- Burst at window boundaries
- Less accurate

**Use Case:** High-throughput APIs where exact accuracy isn't critical

#### Sliding Window Strategy

**Algorithm:**
```
1. Remove expired entries (older than period)
2. Count remaining entries
3. Add new entry with current timestamp
4. Check if count <= limit
```

**Pros:**
- More accurate than fixed window
- Prevents boundary bursts
- Fair distribution

**Cons:**
- Higher memory usage
- Slightly slower

**Use Case:** General purpose rate limiting with good accuracy

#### Token Bucket Strategy

**Algorithm:**
```
1. Calculate tokens to add: tokens = (time_elapsed * rate)
2. Add tokens (max = limit)
3. If tokens >= 1, consume 1 token
4. Update last_update timestamp
```

**Pros:**
- Smooth rate limiting
- Allows controlled bursts
- Flexible

**Cons:**
- More complex
- Requires Lua script

**Use Case:** APIs with variable load, burst support needed

### 2b. Rule Resolution (`app/rules.py`)

Separates **policy** (which limit applies) from **mechanism** (the middleware). All resolvers implement the `RuleResolver` interface and return an `Outcome`.

**Outcome model (illegal states unrepresentable):**
- `Limit(decision)` — apply a concrete `RateLimitDecision(limit, period, identifier)`
- `SKIP` — bypass rate limiting entirely (e.g. enterprise tier, excluded paths)
- `DEFER` — no opinion; ask the next resolver in the chain

**Resolvers:**
- `StaticRuleResolver`: in-memory path rules + defaults; excluded paths → `SKIP`. Terminal (never `DEFER`).
- `RedisOverrideResolver`: reads `ratelimit:tier:<tier>` from Redis for per-subscription overrides → `SKIP` / `Limit` / `DEFER`.
- `ChainResolver`: **Chain of Responsibility** — asks each link in order, the first non-`DEFER` outcome wins; composable.

**Helpers:**
- `as_limit(rule, request, default_key_func)`: the *single* place that applies a key function to build a `RateLimitDecision`, so links never duplicate identifier logic.
- `default_ip_key(request)`: default `ip:<host>` key function.

Because the resolver lives on `app.state.rule_resolver` and `resolve()` is async, limits can be **hot-swapped at runtime** and **evolved per subscription** (via Redis/DB) without code changes.

### 3. Middleware (`app/middleware.py`)

A thin **enforcer**. It owns no rules: it asks `app.state.rule_resolver` for an `Outcome` and enforces it.

**Flow:**
```
Request → Middleware → rule_resolver.resolve() → Outcome
   ├─ Limit  → RateLimiter → Strategy → Redis → add headers → Response/429
   ├─ SKIP   → call_next (bypass)
   └─ DEFER  → log error (misconfig) + call_next
```

**Features:**
- Delegates rule resolution (no `path_rules`/`key_func` knowledge)
- Response header injection
- Fail-open error handling
- Logging

### 4. Decorators (`app/decorators.py`)

Function decorators for endpoint-specific rate limiting.

**Types:**
- `@rate_limit`: Generic rate limiting
- `@user_rate_limit`: Per-user limiting
- `@endpoint_rate_limit`: Per-endpoint limiting

**Advantages:**
- Fine-grained control
- Endpoint-specific limits
- Composable

### 5. Monitoring (`app/monitoring.py`)

Prometheus metrics integration for observability.

**Metrics:**
- `rate_limit_requests_total`: Counter
- `rate_limit_exceeded_total`: Counter
- `rate_limit_check_duration`: Histogram
- `rate_limit_remaining_tokens`: Gauge

## Application Lifecycle

Shared infrastructure is built once in the FastAPI `lifespan` (`app/main.py`):

```
startup:
  init_pool()                       # redis_client: single shared pool
  app.state.redis    = get_client()
  app.state.limiter  = RateLimiter(app.state.redis, ...)
  app.state.rule_resolver = rule_resolver   # ChainResolver([...])
shutdown:
  close_pool()
```

The middleware and endpoints read these off `app.state` per request, so there is exactly one pool and one resolver for the process.

## Data Flow

### Successful Request Flow

```
1. Request arrives
2. Middleware calls rule_resolver.resolve(request) -> Outcome
3. Outcome is a Limit -> RateLimiter.check_rate_limit(decision)
4. Strategy evaluates the limit against Redis
5. X-RateLimit-* headers added to response
6. Request processed by the handler
7. Response returned
```

### Bypassed Request Flow (SKIP)

```
1. Request arrives
2. rule_resolver returns SKIP (excluded path or e.g. enterprise tier)
3. Middleware calls call_next without checking any limit
4. Response returned (no rate-limit headers)
```

### Rate Limited Request Flow

```
1. Request arrives
2. Middleware resolves a Limit and calls the RateLimiter
3. Strategy determines the limit is exceeded
4. 429 response generated
5. Retry-After header added
6. Rate-limit violation logged
7. Response returned
```

## Redis Data Structures

### Fixed Window

```
Key: rate_limit:fixed:{identifier}:{window}
Type: String (counter)
Value: Request count
TTL: 2 * period
```

### Sliding Window

```
Key: rate_limit:sliding:{identifier}
Type: Sorted Set
Members: Timestamp strings
Scores: Unix timestamps
TTL: period
```

### Token Bucket

```
Key: rate_limit:token:{identifier}
Type: Hash
Fields:
  - tokens: Current token count
  - last_update: Last update timestamp
TTL: 2 * period
```

## Configuration Management

### Environment Variables

```
REDIS_HOST: Redis server host
REDIS_PORT: Redis server port
REDIS_DB: Redis database number
REDIS_PASSWORD: Redis password (optional)
REDIS_SSL: Enable SSL (boolean)

RATE_LIMIT_ENABLED: Enable/disable rate limiting
DEFAULT_RATE_LIMIT: Default request limit
DEFAULT_RATE_LIMIT_PERIOD: Default time period

ENVIRONMENT: Application environment
LOG_LEVEL: Logging level
```

### Configuration Hierarchy

```
1. Environment variables (.env)
2. Default values (config.py)
3. Runtime overrides (function parameters)
```

## Scalability Considerations

### Horizontal Scaling

**Challenges:**
- Shared state across instances
- Consistent rate limiting

**Solutions:**
- Centralized Redis
- Redis Cluster for high availability
- Consistent hashing for distribution

### Performance Optimization

**Strategies:**
1. **Connection Pooling**: Reuse Redis connections
2. **Lua Scripts**: Atomic operations in Redis
3. **Pipeline Commands**: Batch Redis operations
4. **Async I/O**: Non-blocking operations

### High Availability

**Components:**
1. **Redis Sentinel**: Automatic failover
2. **Redis Cluster**: Distributed data
3. **Circuit Breaker**: Fail gracefully
4. **Fallback Mode**: Disable rate limiting on Redis failure

## Security Considerations

### Attack Vectors

1. **DDoS**: Overwhelm with requests
   - **Mitigation**: Strict rate limits, IP blocking

2. **Distributed Attacks**: Multiple IPs
   - **Mitigation**: User-based limits, behavioral analysis

3. **Redis Access**: Unauthorized access
   - **Mitigation**: Password, SSL, network isolation

### Best Practices

1. Use strong Redis passwords
2. Enable SSL for Redis connections
3. Implement IP whitelisting
4. Monitor for unusual patterns
5. Log rate limit violations
6. Implement progressive penalties

## Testing Strategy

### Unit Tests

- Test each strategy independently
- Mock Redis for isolation
- Test edge cases and boundaries

### Integration Tests

- Test with real Redis (fakeredis)
- Test middleware integration
- Test decorator functionality

### Load Tests

- Simulate high traffic
- Test concurrent requests
- Measure performance
- Verify rate limiting accuracy

## Monitoring and Observability

### Metrics to Track

1. **Request Metrics**
   - Total requests
   - Rate limited requests
   - Success rate

2. **Performance Metrics**
   - Response time
   - Redis latency
   - Check duration

3. **Business Metrics**
   - Top rate limited users
   - Endpoint usage
   - Time-based patterns

### Alerting

**Critical Alerts:**
- Redis connection failure
- High rate limit violation rate
- Unusual traffic patterns

**Warning Alerts:**
- Increased latency
- High memory usage
- Approaching limits

## Extension Points

### Custom Strategies

Implement `RateLimiterStrategy` interface:

```python
class CustomStrategy(RateLimiterStrategy):
    async def is_allowed(self, key, limit, period):
        # Custom logic
        pass
    
    async def reset(self, key):
        # Custom reset
        pass
```

### Custom Identifiers

Provide custom key function:

```python
def custom_key(request: Request) -> str:
    # Extract custom identifier
    return f"custom:{value}"
```

### Custom Resolvers

Implement the `RuleResolver` interface and slot it into the chain to evolve policy without touching the middleware:

```python
from app.rules import RuleResolver, Outcome, SKIP, DEFER, as_limit, RateLimitRule

class DatabaseOverrideResolver(RuleResolver):
    async def resolve(self, request) -> Outcome:
        plan = await load_plan_from_db(request)   # your lookup
        if plan is None:
            return DEFER                            # let the next link decide
        if plan.unlimited:
            return SKIP                             # bypass entirely
        return as_limit(RateLimitRule(plan.limit, plan.period), request)

# Compose: most specific/dynamic first, terminal resolver last
app.state.rule_resolver = ChainResolver([
    DatabaseOverrideResolver(),
    StaticRuleResolver(default_limit=100, default_period=60),
])
```

### Custom Monitoring

Extend `RateLimitMonitor`:

```python
class CustomMonitor(RateLimitMonitor):
    @staticmethod
    def record_check(identifier, result, duration, strategy):
        # Custom metrics
        super().record_check(identifier, result, duration, strategy)
        # Additional tracking
```

## Future Enhancements

1. **Distributed Rate Limiting**: Across multiple data centers
2. **Machine Learning**: Adaptive rate limits
3. **GraphQL Support**: Query complexity-based limiting
4. **WebSocket Support**: Connection-based limiting
5. **Rate Limit Templates**: Predefined limit configurations
6. **Analytics Dashboard**: Visual rate limit insights
