"""WebSocket manager for real-time browser updates."""

import asyncio
import json
import logging
import time
from typing import Set, Dict, Any

from fastapi import WebSocket

logger = logging.getLogger("propview.websocket")


class WebSocketManager:
    """Manages WebSocket connections and broadcasts updates to all clients."""

    MAX_CONNECTIONS = 20

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._message_queue: asyncio.Queue = asyncio.Queue()

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept a new WebSocket connection if under the limit."""
        if len(self.active_connections) >= self.MAX_CONNECTIONS:
            await websocket.close(code=1013, reason="Too many connections")
            logger.warning(f"WebSocket rejected: at {self.MAX_CONNECTIONS} connection limit")
            return False
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected ({len(self.active_connections)} total)")
        return True

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected ({len(self.active_connections)} total)")

    async def broadcast(self, message: Dict[str, Any]):
        """Send a message to all connected WebSocket clients."""
        if not self.active_connections:
            return

        # Serialize once
        try:
            data = json.dumps(message, default=str)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize WebSocket message: {e}")
            return

        # Send to all clients, removing dead connections
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.active_connections.discard(ws)

    async def send_to(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific WebSocket client."""
        try:
            data = json.dumps(message, default=str)
            await websocket.send_text(data)
        except Exception as e:
            logger.error(f"Failed to send to WebSocket: {e}")
            self.active_connections.discard(websocket)

    @property
    def client_count(self) -> int:
        return len(self.active_connections)
