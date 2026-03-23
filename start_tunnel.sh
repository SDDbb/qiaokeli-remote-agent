#!/bin/bash
# Start OpenHands tunnel with clean environment

# Kill any existing tunnel processes
pkill -f "python.*openhands_tunnel_server.py" 2>/dev/null
kill -9 `lsof -t -i :8765` 2>/dev/null
sleep 2

# Clean environment and start
unset LD_LIBRARY_PATH
cd /home/zhujintao/桌面/qiaokeli-remote-agent
python scripts/openhands_tunnel_server.py >> tunnel.log 2>&1 &
disown $!

sleep 2
if ss -tulpn | grep -q :8765; then
    echo "✅ Tunnel server started successfully on port 8765"
    echo "👉 Tailscale: ws://100.100.198.35:8765"
    tailscale status | head -5
else
    echo "❌ Failed to start tunnel, check logs:"
    tail -20 tunnel.log
fi
