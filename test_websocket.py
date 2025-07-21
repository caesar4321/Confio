#!/usr/bin/env python3
"""
Simple WebSocket test script for P2P trade chat
"""
import asyncio
import websockets
import json
import sys

async def test_websocket():
    # Test connection with token
    trade_id = sys.argv[1] if len(sys.argv) > 1 else "2"
    token = sys.argv[2] if len(sys.argv) > 2 else ""
    
    if token:
        uri = f"ws://localhost:8000/ws/trade/{trade_id}/?token={token}"
        print(f"Testing WebSocket connection to: ws://localhost:8000/ws/trade/{trade_id}/?token=TOKEN_HIDDEN")
    else:
        uri = f"ws://localhost:8000/ws/trade/{trade_id}/"
        print(f"Testing WebSocket connection to: {uri}")
        print("❗ No token provided, connection may be rejected")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connected successfully!")
            
            # Wait for any initial messages
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                print(f"📨 Received: {message}")
            except asyncio.TimeoutError:
                print("🕐 No initial message received (timeout)")
            
            # Send a test message
            test_message = {
                "type": "message",
                "content": "Hello from test script!"
            }
            await websocket.send(json.dumps(test_message))
            print(f"📤 Sent: {test_message}")
            
            # Wait for response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"📨 Response: {response}")
            except asyncio.TimeoutError:
                print("🕐 No response received (timeout)")
                
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket())