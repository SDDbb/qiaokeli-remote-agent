#!/usr/bin/env python3
"""
OpenHands Interactive Tunnel Server for Android Remote Vibe Coding.

This server:
- Runs on your Fedora desktop, proxies a persistent OpenHands CLI process
- Exposes a WebSocket endpoint over Tailscale for Android clients
- Supports interactive I/O with full ANSI color and terminal capabilities
- Handles automatic reconnection without losing the OpenHands session
- Works with any modern WebSocket client on Android (e.g. Termux, NetHunter)

Author: Qiaokeli
"""
from __future__ import annotations

# Fix LD_LIBRARY_PATH pollution from OpenHands AppImage
# It leaves behind incompatible OPENSSL libraries that break system Python
import os
if 'LD_LIBRARY_PATH' in os.environ:
    # The dynamic linker has already loaded bad libraries if they exist,
    # but at least we can clear it for any new processes spawned later
    print(f"[tunnel] Cleaning LD_LIBRARY_PATH from AppImage: {os.environ.get('LD_LIBRARY_PATH')}", flush=True)
    del os.environ['LD_LIBRARY_PATH']

import asyncio
import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".config" / "qiaokeli-remote-agent"
CONFIG_FILE = CONFIG_DIR / "tunnel_config.env"

DEFAULT_CONFIG = {
    "QIAOKELI_OH_TUNNEL_HOST": "0.0.0.0",
    "QIAOKELI_OH_TUNNEL_PORT": "8765",
    "QIAOKELI_OH_TUNNEL_WORKDIR": str(Path.home() / "桌面" / "openhands-playground"),
    "QIAOKELI_OH_TUNNEL_OPENHANDS_CMD": str(Path.home() / "桌面" / "openhands-playground/.venv/bin/python -m openhands.core.main"),
    "QIAOKELI_OH_TUNNEL_MAX_OUTPUT_BUFFER": "1048576",
    "QIAOKELI_OH_TUNNEL_PING_INTERVAL": "30",
    "QIAOKELI_OH_TUNNEL_AUTH_TOKEN": "",  # Leave empty for no auth (safe on Tailscale private net)
}


@dataclass
class OpenHandsProcess:
    """Wrapper around the persistent OpenHands CLI subprocess."""
    process: asyncio.subprocess.Process
    output_buffer: list[str] = field(default_factory=list)
    max_buffer_size: int = 200000
    connected_clients: Set[WebSocketServerProtocol] = field(default_factory=set)
    _read_task: Optional[asyncio.Task] = None
    _output_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    async def spawn(cls, cmd: str, cwd: str, max_buffer: int) -> OpenHandsProcess:
        """Spawn a new OpenHands process. Compatible with Python 3.14."""
        # Use bash to get job control
        shell_cmd = f"cd {cwd} && {cmd}"
        print(f"[tunnel] Spawning OpenHands with command: {shell_cmd}", flush=True)
        
        # Create new process group for proper signal handling
        def preexec_fn():
            os.setsid()
        
        # Use asyncio directly - compatible with Python 3.8+ including 3.14
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=preexec_fn
        )
        
        return cls(
            process=process,
            max_buffer_size=max_buffer
        )

    def start_reader(self, on_output: Callable[[str], None]) -> None:
        """Start the background output reader."""
        self._read_task = asyncio.create_task(self._read_loop(on_output))

    async def _read_loop(self, on_output: Callable[[str], None]) -> None:
        """Continuously read from process stdout."""
        while True:
            try:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    # EOF - process exited
                    print("[tunnel] OpenHands process EOF, exiting reader", flush=True)
                    break
                
                # Decode, handle any encoding errors
                text = chunk.decode('utf-8', errors='replace')
                
                async with self._output_lock:
                    self.output_buffer.append(text)
                    # Trim buffer if too large
                    total_len = sum(len(s) for s in self.output_buffer)
                    if total_len > self.max_buffer_size:
                        # Remove older chunks to keep buffer under limit
                        while total_len > self.max_buffer_size and len(self.output_buffer) > 1:
                            removed = self.output_buffer.pop(0)
                            total_len -= len(removed)
                
                # Broadcast to all connected clients
                await on_output(text)
            except Exception as e:
                print(f"[tunnel] Output reader error: {e}", flush=True)
                await asyncio.sleep(0.1)
                break
        
        print("[tunnel] OpenHands process has exited", flush=True)

    async def send_input(self, text: str) -> None:
        """Send input text to OpenHands stdin."""
        if self.process.stdin is not None:
            try:
                self.process.stdin.write(text.encode('utf-8'))
                await self.process.stdin.drain()
            except Exception as e:
                print(f"[tunnel] Failed to send input: {e}", flush=True)

    async def broadcast_output(self, text: str) -> None:
        """Send output to all connected clients."""
        if not self.connected_clients:
            return
        
        disconnected = set()
        for client in self.connected_clients:
            try:
                await client.send(json.dumps({
                    "type": "output",
                    "data": text,
                    "timestamp": datetime.now(UTC).isoformat()
                }))
            except Exception:
                disconnected.add(client)
        
        # Remove disconnected clients
        for client in disconnected:
            self.connected_clients.discard(client)

    def get_full_buffer(self) -> str:
        """Get the complete buffered output for new clients."""
        return ''.join(self.output_buffer)

    async def terminate(self) -> None:
        """Terminate the OpenHands process."""
        if self._read_task is not None and not self._read_task.done():
            self._read_task.cancel()
        
        if self.process.returncode is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                await asyncio.sleep(0.5)
                if self.process.returncode is None:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except Exception:
                pass


class OpenHandsTunnelServer:
    """WebSocket tunnel server for remote OpenHands access."""
    
    def __init__(
        self,
        host: str,
        port: int,
        workdir: str,
        openhands_cmd: str,
        max_buffer_size: int,
        ping_interval: float,
        auth_token: Optional[str] = None
    ):
        self.host = host
        self.port = port
        self.workdir = workdir
        self.openhands_cmd = openhands_cmd
        self.max_buffer_size = max_buffer_size
        self.ping_interval = ping_interval
        self.auth_token = auth_token
        self.oh_process: Optional[OpenHandsProcess] = None
        self.server: Optional[websockets.WebSocketServer] = None

    async def handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a new client connection."""
        client_addr = websocket.remote_address
        print(f"[tunnel] New client connected from: {client_addr}", flush=True)

        # Authenticate if token is configured
        if self.auth_token:
            try:
                first_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(first_msg)
                if data.get("type") != "auth" or data.get("token") != self.auth_token:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Authentication failed"
                    }))
                    await websocket.close(1008, "Authentication failed")
                    print(f"[tunnel] Client {client_addr} auth failed", flush=True)
                    return
                # Auth success
                await websocket.send(json.dumps({
                    "type": "auth_ok",
                    "message": "Authenticated successfully"
                }))
                print(f"[tunnel] Client {client_addr} authenticated", flush=True)
            except (asyncio.TimeoutError, json.JSONDecodeError):
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": "Invalid auth handshake"
                }))
                await websocket.close(1008, "Invalid auth")
                return

        # Ensure OpenHands process is running
        if self.oh_process is None:
            await self._spawn_openhands()
        if self.oh_process is None:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Failed to start OpenHands process"
            }))
            await websocket.close()
            return

        # Add client to broadcast list
        self.oh_process.connected_clients.add(websocket)
        
        # Send buffered output history to new client
        full_output = self.oh_process.get_full_buffer()
        try:
            await websocket.send(json.dumps({
                "type": "history",
                "data": full_output,
                "timestamp": datetime.now(UTC).isoformat()
            }))
        except Exception as e:
            print(f"[tunnel] Failed to send history to {client_addr}: {e}", flush=True)
            self.oh_process.connected_clients.discard(websocket)
            return

        try:
            # Process messages from client
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    if msg_type == "input":
                        # User input to forward to OpenHands
                        input_text = data.get("data", "")
                        if input_text and self.oh_process:
                            await self.oh_process.send_input(input_text)
                    
                    elif msg_type == "ping":
                        # Client ping for keepalive
                        await websocket.send(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now(UTC).isoformat()
                        }))
                    
                    elif msg_type == "restart":
                        # Request to restart OpenHands process
                        if self.oh_process:
                            await self.oh_process.terminate()
                        await self._spawn_openhands()
                        print(f"[tunnel] OpenHands restarted by {client_addr}", flush=True)
                        # Send new history
                        if self.oh_process:
                            await websocket.send(json.dumps({
                                "type": "history",
                                "data": self.oh_process.get_full_buffer(),
                                "timestamp": datetime.now(UTC).isoformat()
                            }))
                
                except json.JSONDecodeError:
                    # Raw text - treat as direct input (for simple clients)
                    if self.oh_process:
                        await self.oh_process.send_input(message + "\n")

        except Exception as e:
            # Client disconnected normally
            print(f"[tunnel] Client {client_addr} disconnected: {e}", flush=True)
        finally:
            if self.oh_process:
                self.oh_process.connected_clients.discard(websocket)
            print(f"[tunnel] Client {client_addr} removed", flush=True)

    async def _spawn_openhands(self) -> None:
        """Spawn the OpenHands process."""
        if self.oh_process is not None:
            await self.oh_process.terminate()
        
        self.oh_process = await OpenHandsProcess.spawn(
            self.openhands_cmd,
            self.workdir,
            self.max_buffer_size
        )
        # Start output reader that broadcasts to clients
        self.oh_process.start_reader(lambda text: self.oh_process.broadcast_output(text))

    async def start(self) -> None:
        """Start the WebSocket server."""
        print(f"[tunnel] Starting OpenHands tunnel server on {self.host}:{self.port}", flush=True)
        print(f"[tunnel] Working directory: {self.workdir}", flush=True)
        print(f"[tunnel] OpenHands command: {self.openhands_cmd}", flush=True)
        
        # Spawn initial OpenHands process
        await self._spawn_openhands()
        
        # Start WebSocket server - compatible with websockets 12+
        server = await websockets.serve(
            self.handle_client,
            self.host,
            self.port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_interval * 3,
            max_size=None  # No size limit for messages
        )
        self.server = server
        await asyncio.Future()  # run forever

    async def shutdown(self, sig: signal.Signals) -> None:
        """Graceful shutdown."""
        print(f"\n[tunnel] Received signal {sig.name}, shutting down", flush=True)
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        if self.oh_process is not None:
            await self.oh_process.terminate()
        print("[tunnel] Shutdown complete", flush=True)


def ensure_config() -> dict[str, str]:
    """Load or create configuration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    example = PROJECT_ROOT / "config" / "tunnel_config.env.example"
    
    if not CONFIG_FILE.exists():
        # Copy the example
        CONFIG_FILE.write_text(example.read_text())
    
    # Parse config
    values = dict(DEFAULT_CONFIG)
    for raw_line in CONFIG_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    
    return values


def get_tailscale_ip() -> str:
    """Get Tailscale IP for connection info."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return ""


async def main() -> int:
    """Main entry point."""
    config = ensure_config()
    
    # Parse config
    host = config["QIAOKELI_OH_TUNNEL_HOST"]
    port = int(config["QIAOKELI_OH_TUNNEL_PORT"])
    workdir = str(Path(config["QIAOKELI_OH_TUNNEL_WORKDIR"]).expanduser())
    openhands_cmd = config["QIAOKELI_OH_TUNNEL_OPENHANDS_CMD"]
    max_buffer = int(config["QIAOKELI_OH_TUNNEL_MAX_OUTPUT_BUFFER"])
    ping_interval = float(config["QIAOKELI_OH_TUNNEL_PING_INTERVAL"])
    auth_token = config.get("QIAOKELI_OH_TUNNEL_AUTH_TOKEN", "").strip()
    auth_token = auth_token if auth_token else None
    
    # Print connection info
    ts_ip = get_tailscale_ip()
    if ts_ip:
        print(f"[tunnel] Tailscale IP available: ws://{ts_ip}:{port}", flush=True)
    else:
        print(f"[tunnel] Connection URL: ws://<your-ip>:{port}", flush=True)
    
    # Create and start server
    server = OpenHandsTunnelServer(
        host=host,
        port=port,
        workdir=workdir,
        openhands_cmd=openhands_cmd,
        max_buffer_size=max_buffer,
        ping_interval=ping_interval,
        auth_token=auth_token
    )
    
    # Setup signal handlers for graceful shutdown
    def handle_shutdown(sig):
        asyncio.create_task(server.shutdown(sig))
    
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, handle_shutdown, sig)
    
    try:
        await server.start()
    except asyncio.CancelledError:
        print("[tunnel] Server cancelled", flush=True)
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[tunnel] Keyboard interrupt, exiting", flush=True)
        sys.exit(1)
