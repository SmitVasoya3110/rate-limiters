# Architecture Documentation

## System Overview

The API Rate Limiter is built with a modular architecture that separates concerns and allows for easy extension and customization.

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐         ┌─────────────────┐              │
│  │  Middleware  │────────▶│   Decorators    │              │
│  └──────────────┘         └─────────────────┘              │
│         │                          │                         │
│         └──────────┬───────────────┘                         │
│                    ▼                                         │
│         ┌──────────────────────┐                            │
│         │   Rate Limiter Core  │                            │
│         └──────────────────────┘                            │
│                    │                                         │
│         ┌──────────┴──────────┐                             │
│         ▼                     ▼                              │
│  ┌─────────────┐      ┌─────────────┐                      │
│  │  Strategies │      │  Monitoring │                       │
│  └─────────────┘      └─────────────┘                      │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐                                            │
│  │    Redis    │                                            │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Rate Limiter Core (`app/rate_limiter/limiter.py`)

The central component that orchestrates rate limiting operations.

**Responsibilities:**
- Manage Redis connections
- Initialize and switch between strategies
- Provide high-level API for rate limit checks
- Generate identifiers from request context

**Key Methods:**
- `connect()`: Establish Redis connection
- `check_rate_limit()`: Check if request is allowed
- `reset_limit()`: Reset rate limit for identifier
- `get_identifier()`: Generate unique identifier

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

### 3. Middleware (`app/middleware.py`)

FastAPI middleware for global rate limiting.

**Flow:**
```
Request → Middleware → Rate Limiter → Strategy → Redis
                ↓
         Add Headers
                ↓
         Response/429
```

**Features:**
- Automatic rate limit checking
- Response header injection
- Error handling
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

## Data Flow

### Successful Request Flow

```
1. Request arrives
2. Middleware/Decorator extracts identifier
3. Rate Limiter checks Redis
4. Strategy evaluates limit
5. Headers added to response
6. Request processed
7. Response returned
```

### Rate Limited Request Flow

```
1. Request arrives
2. Middleware/Decorator extracts identifier
3. Rate Limiter checks Redis
4. Strategy determines limit exceeded
5. 429 response generated
6. Retry-After header added
7. Error logged
8. Response returned
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
