import asyncio
import redis.asyncio as aioredis

async def test_redis():
    try:
        r = aioredis.from_url("redis://localhost:6382/0")
        print("Pinging Redis...")
        res = await r.ping()
        print(f"Redis ping result: {res}")
        await r.close()
    except Exception as e:
        print(f"Redis connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_redis())
