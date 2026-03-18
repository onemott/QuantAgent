
import httpx
import asyncio

async def test_start_replay():
    async with httpx.AsyncClient() as client:
        # 1. Create session first
        payload = {
            "strategy_id": 1,
            "symbol": "BTCUSDT",
            "start_time": "2026-03-15T00:00:00Z",
            "end_time": "2026-03-16T00:00:00Z",
            "speed": 60,
            "initial_capital": 100000.0
        }
        res = await client.post("http://localhost:8000/api/v1/replay/create", json=payload)
        print(f"Create status: {res.status_code}")
        if res.status_code != 200:
            print(f"Create error: {res.text}")
            return
        
        data = res.json()
        session_id = data["replay_session_id"]
        print(f"Session ID: {session_id}")
        
        # 2. Start session
        res = await client.post(f"http://localhost:8000/api/v1/replay/{session_id}/start")
        print(f"Start status: {res.status_code}")
        print(f"Start response: {res.text}")

if __name__ == "__main__":
    asyncio.run(test_start_replay())
