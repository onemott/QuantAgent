
import asyncio
import websockets
import json
import logging
import sys

# Configure logging to see detailed debug info
logging.basicConfig(level=logging.DEBUG)

async def test_ws():
    uri = "ws://localhost:8000/ws/market"
    print(f"Connecting to {uri}...")
    try:
        # Use open_timeout to avoid hanging indefinitely if handshake fails
        async with websockets.connect(uri, open_timeout=5) as websocket:
            print("Connected!")
            
            # Subscribe
            msg = {"action": "subscribe", "symbol": "BTCUSDT"}
            await websocket.send(json.dumps(msg))
            print(f"Sent: {msg}")
            
            # Wait for response
            while True:
                response = await websocket.recv()
                print(f"Received: {response}")
                break
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"Invalid status code: {e.status_code}")
        print(f"Response headers: {e.headers}")
    except Exception as e:
        print(f"Connection failed: {e}")
        # import traceback
        # traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ws())
