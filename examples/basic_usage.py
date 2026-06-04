import asyncio
from app.rate_limiter import RateLimiter, StrategyType
from app.redis_client import init_pool, get_client, close_pool


async def basic_example():
    print("=== Basic Rate Limiter Example ===\n")
    
    init_pool()
    limiter = RateLimiter(get_client(), strategy_type=StrategyType.SLIDING_WINDOW)
    
    identifier = "user:john_doe"
    limit = 5
    period = 60
    
    print(f"Testing rate limit: {limit} requests per {period} seconds")
    print(f"Identifier: {identifier}\n")
    
    for i in range(7):
        result = await limiter.check_rate_limit(identifier, limit, period)
        
        status = "✓ ALLOWED" if result.allowed else "✗ BLOCKED"
        print(f"Request {i+1}: {status}")
        print(f"  Remaining: {result.remaining}/{result.limit}")
        print(f"  Reset at: {result.reset_at.strftime('%H:%M:%S')}")
        
        if not result.allowed:
            print(f"  Retry after: {result.retry_after} seconds")
        print()
    
    print("\nResetting rate limit...")
    await limiter.reset_limit(identifier)
    
    result = await limiter.check_rate_limit(identifier, limit, period)
    print(f"After reset - Allowed: {result.allowed}, Remaining: {result.remaining}")
    
    await close_pool()


async def compare_strategies():
    print("\n=== Comparing Rate Limiting Strategies ===\n")
    
    strategies = [
        (StrategyType.FIXED_WINDOW, "Fixed Window"),
        (StrategyType.SLIDING_WINDOW, "Sliding Window"),
        (StrategyType.TOKEN_BUCKET, "Token Bucket"),
    ]
    
    for strategy_type, name in strategies:
        print(f"\n{name} Strategy:")
        print("-" * 40)
        
        init_pool()
        limiter = RateLimiter(get_client(), strategy_type=strategy_type)
        
        identifier = f"test:{name.lower().replace(' ', '_')}"
        limit = 3
        period = 10
        
        for i in range(5):
            result = await limiter.check_rate_limit(identifier, limit, period)
            status = "✓" if result.allowed else "✗"
            print(f"  Request {i+1}: {status} (Remaining: {result.remaining})")
        
        await close_pool()


async def burst_handling():
    print("\n=== Token Bucket Burst Handling ===\n")
    
    init_pool()
    limiter = RateLimiter(get_client(), strategy_type=StrategyType.TOKEN_BUCKET)
    
    identifier = "burst_test"
    limit = 10
    period = 5
    
    print(f"Limit: {limit} requests per {period} seconds")
    print("Sending burst of requests...\n")
    
    for i in range(12):
        result = await limiter.check_rate_limit(identifier, limit, period)
        status = "✓ ALLOWED" if result.allowed else "✗ BLOCKED"
        print(f"Request {i+1}: {status} (Remaining: {result.remaining})")
    
    print("\nWaiting 2 seconds for token refill...")
    await asyncio.sleep(2)
    
    print("\nAfter refill:")
    for i in range(3):
        result = await limiter.check_rate_limit(identifier, limit, period)
        status = "✓ ALLOWED" if result.allowed else "✗ BLOCKED"
        print(f"Request {i+1}: {status} (Remaining: {result.remaining})")
    
    await close_pool()


async def custom_identifiers():
    print("\n=== Custom Identifier Examples ===\n")
    
    init_pool()
    limiter = RateLimiter(get_client(), strategy_type=StrategyType.SLIDING_WINDOW)
    
    examples = [
        {"ip": "192.168.1.1", "user": "john"},
        {"ip": "192.168.1.2", "user": "jane"},
        {"endpoint": "/api/data", "ip": "192.168.1.1"},
    ]
    
    for example in examples:
        identifier = limiter.get_identifier(**example)
        result = await limiter.check_rate_limit(identifier, limit=100, period=60)
        
        print(f"Identifier: {identifier}")
        print(f"  Allowed: {result.allowed}")
        print(f"  Remaining: {result.remaining}/{result.limit}")
        print()
    
    await close_pool()


async def main():
    try:
        await basic_example()
        await compare_strategies()
        await burst_handling()
        await custom_identifiers()
        
        print("\n" + "="*50)
        print("All examples completed successfully!")
        print("="*50)
        
    except Exception as e:
        print(f"\nError: {e}")
        print("\nMake sure Redis is running:")
        print("  docker run -d -p 6379:6379 redis:latest")


if __name__ == "__main__":
    asyncio.run(main())
