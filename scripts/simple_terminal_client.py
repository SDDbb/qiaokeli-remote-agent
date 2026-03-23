#!/usr/bin/env python3
"""
Simple terminal client for OpenHands tunnel.
Run this on your Android Termux to connect to the tunnel.

Usage:
    python simple_terminal_client.py ws://100.x.y.z:8765 [auth_token]
"""
import asyncio
import json
import sys
import threading

import websockets


class SimpleTerminalClient:
    """Simple terminal client that connects to the OpenHands tunnel."""
    
    def __init__(self, url: str, auth_token: str = None):
        self.url = url
        self.auth_token = auth_token
        self.websocket = None
        self.running = True
    
    async def connect(self):
        """Connect to the tunnel server."""
        try:
            async with websockets.connect(self.url) as websocket:
                self.websocket = websocket
                print(f"Connected to {self.url}")
                
                # Authenticate if needed
                if self.auth_token:
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "token": self.auth_token
                    }))
                    response = await websocket.recv()
                    data = json.loads(response)
                    if data.get("type") != "auth_ok":
                        print(f"Authentication failed: {data.get('message', 'Unknown error')}")
                        return
                    print("Authenticated ✓")
                
                # Start reader thread for stdin
                thread = threading.Thread(target=self.read_stdin, daemon=True)
                thread.start()
                
                # Process messages from server
                async for message in websocket:
                    if not self.running:
                        break
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        
                        if msg_type == "output":
                            # Server output - print directly to terminal (preserves ANSI colors)
                            print(data.get("data", ""), end="", flush=True)
                        elif msg_type == "history":
                            # Full history for reconnect - print all at once
                            print(data.get("data", ""), end="", flush=True)
                        elif msg_type == "auth_ok":
                            pass  # Already handled
                        elif msg_type == "pong":
                            pass  # Keepalive response, ignore
                        elif msg_type == "error":
                            print(f"\n[ERROR] {data.get('message')}", flush=True)
                    except json.JSONDecodeError:
                        # Raw output - print directly
                        print(message, end="", flush=True)
            
            print("\nDisconnected from server")
        except Exception as e:
            print(f"\nConnection error: {e}")
    
    def read_stdin(self):
        """Read from stdin in background thread and send to server."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop in thread, create new
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    self.running = False
                    break
                if self.websocket and not self.websocket.closed:
                    # Send as input
                    future = asyncio.run_coroutine_threadsafe(
                        self.send_input(line), loop
                    )
                    try:
                        future.result(timeout=5)
                    except Exception as e:
                        print(f"\n[Client] Failed to send input: {e}", flush=True)
                        break
            except Exception as e:
                print(f"\n[Client] Reader thread error: {e}", flush=True)
                break
    
    async def send_input(self, text: str):
        """Send input to server."""
        if self.websocket:
            try:
                await self.websocket.send(json.dumps({
                    "type": "input",
                    "data": text
                }))
            except Exception:
                self.running = False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"\nUsage: {sys.argv[0]} ws://<server-ip>:<port> [auth-token]")
        sys.exit(1)
    
    url = sys.argv[1]
    auth_token = sys.argv[2] if len(sys.argv) > 2 else None
    
    client = SimpleTerminalClient(url, auth_token)
    asyncio.run(client.connect())


if __name__ == "__main__":
    main()
