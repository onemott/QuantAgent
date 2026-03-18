import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://127.0.0.1:8002/ws/market"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri, open_timeout=20.0) as websocket:
            print("Connected successfully!")
            
            # Send subscribe message
            msg = {"action": "subscribe", "symbol": "BTCUSDT"}
            await websocket.send(json.dumps(msg))
            print(f"Sent: {msg}")
            
            # Wait for response
            while True:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    print(f"Received: {response[:200]}...")
                    
                    data = json.loads(response)
                    if data.get("type") == "ticker":
                        print("Ticker data received! WebSocket is working.")
                        break
                except asyncio.TimeoutError:
                    print("Timeout waiting for data. But connection is open.")
                    break
                    
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
