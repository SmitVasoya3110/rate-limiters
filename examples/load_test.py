import asyncio
import time
from typing import List
import httpx


async def make_request(client: httpx.AsyncClient, url: str, request_num: int):
    try:
        start_time = time.time()
        response = await client.get(url)
        duration = time.time() - start_time
        
        return {
            "request_num": request_num,
            "status_code": response.status_code,
            "duration": duration,
            "headers": {
                "limit": response.headers.get("X-RateLimit-Limit"),
                "remaining": response.headers.get("X-RateLimit-Remaining"),
                "reset": response.headers.get("X-RateLimit-Reset"),
            }
        }
    except Exception as e:
        return {
            "request_num": request_num,
            "error": str(e)
        }


async def load_test(url: str, num_requests: int, concurrent: int = 10):
    print(f"\n=== Load Testing: {url} ===")
    print(f"Total requests: {num_requests}")
    print(f"Concurrent requests: {concurrent}\n")
    
    results = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for batch_start in range(0, num_requests, concurrent):
            batch_size = min(concurrent, num_requests - batch_start)
            tasks = [
                make_request(client, url, batch_start + i)
                for i in range(batch_size)
            ]
            
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            
            await asyncio.sleep(0.1)
    
    return results


def analyze_results(results: List[dict]):
    print("\n=== Results Analysis ===\n")
    
    total = len(results)
    successful = sum(1 for r in results if r.get("status_code") == 200)
    rate_limited = sum(1 for r in results if r.get("status_code") == 429)
    errors = sum(1 for r in results if "error" in r)
    
    print(f"Total requests: {total}")
    print(f"Successful (200): {successful} ({successful/total*100:.1f}%)")
    print(f"Rate limited (429): {rate_limited} ({rate_limited/total*100:.1f}%)")
    print(f"Errors: {errors} ({errors/total*100:.1f}%)")
    
    if results:
        durations = [r["duration"] for r in results if "duration" in r]
        if durations:
            avg_duration = sum(durations) / len(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            
            print(f"\nResponse times:")
            print(f"  Average: {avg_duration*1000:.2f}ms")
            print(f"  Min: {min_duration*1000:.2f}ms")
            print(f"  Max: {max_duration*1000:.2f}ms")
    
    print("\nFirst 10 requests:")
    for i, result in enumerate(results[:10]):
        if "status_code" in result:
            status = result["status_code"]
            remaining = result["headers"].get("remaining", "N/A")
            print(f"  {i+1}. Status: {status}, Remaining: {remaining}")


async def test_endpoint(base_url: str, endpoint: str, num_requests: int):
    url = f"{base_url}{endpoint}"
    results = await load_test(url, num_requests, concurrent=5)
    analyze_results(results)


async def main():
    base_url = "http://localhost:8000"
    
    print("="*60)
    print("API Rate Limiter - Load Testing")
    print("="*60)
    
    print("\nMake sure the API is running:")
    print("  python -m app.main")
    print("\nPress Enter to start testing...")
    input()
    
    endpoints = [
        ("/public", 50, "Public endpoint (100 req/min)"),
        ("/api/limited", 20, "Limited endpoint (10 req/min)"),
        ("/api/strict", 15, "Strict endpoint (5 req/min)"),
    ]
    
    for endpoint, num_requests, description in endpoints:
        print(f"\n{'='*60}")
        print(f"Testing: {description}")
        print(f"{'='*60}")
        await test_endpoint(base_url, endpoint, num_requests)
        await asyncio.sleep(2)
    
    print("\n" + "="*60)
    print("Load testing completed!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
