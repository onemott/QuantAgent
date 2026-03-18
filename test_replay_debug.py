
import requests
import time
import json

def test_replay_with_logs():
    backend_url = "http://localhost:8002"
    
    # 1. Create session
    payload = {
        "strategy_id": 1,
        "symbol": "BTCUSDT",
        "start_time": "2026-03-15T00:00:00Z",
        "end_time": "2026-03-15T00:05:00Z",
        "speed": 1,  # Use 1x for debugging
        "initial_capital": 100000.0,
        "strategy_type": "ma",
        "params": {"fast_period": 10, "slow_period": 30}
    }
    print("Creating replay session...")
    res = requests.post(f"{backend_url}/api/v1/replay/create", json=payload)
    print(f"Create status: {res.status_code}")
    print(f"Create response: {res.text}")
    
    if res.status_code != 200:
        return
    
    data = res.json()
    session_id = data["replay_session_id"]
    print(f"Session ID: {session_id}")
    
    # 2. Start session
    print("\nStarting replay...")
    res = requests.post(f"{backend_url}/api/v1/replay/{session_id}/start")
    print(f"Start status: {res.status_code}")
    print(f"Start response: {res.text}")
    
    if res.status_code != 200:
        return
    
    # 3. Poll status
    print("\nPolling status for 20 seconds...")
    for i in range(40):
        time.sleep(0.5)
        try:
            res = requests.get(f"{backend_url}/api/v1/replay/{session_id}/status")
            if res.status_code == 200:
                status = res.json()
                elapsed = i * 0.5
                print(f"[{elapsed:.1f}s] Status: {status['status']}, "
                      f"Progress: {status['progress']*100:.1f}%, "
                      f"Time: {status['current_simulated_time']}, "
                      f"PNL: ${status['pnl']:.2f}")
                
                if status['status'] in ['completed', 'failed']:
                    print(f"\nReplay finished with status: {status['status']}")
                    break
            else:
                print(f"[{i*0.5:.1f}s] Error getting status: {res.status_code}")
        except Exception as e:
            print(f"[{i*0.5:.1f}s] Exception: {e}")

if __name__ == "__main__":
    test_replay_with_logs()
