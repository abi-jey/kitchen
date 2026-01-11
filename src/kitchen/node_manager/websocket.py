"""WebSocket support for live updates."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Set, Dict, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for live updates."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        data = json.dumps(message, default=self._json_serializer)
        disconnected: Set[WebSocket] = set()

        async with self._lock:
            connections = list(self.active_connections)

        for connection in connections:
            try:
                await connection.send_text(data)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                self.active_connections -= disconnected

    @staticmethod
    def _json_serializer(obj: Any) -> str:
        """JSON serializer for objects not serializable by default."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# Global connection manager instance
manager = ConnectionManager()


class LiveUpdate(BaseModel):
    """Structure for live update messages."""
    type: str  # 'nodes_update', 'connectivity_update', 'stats_update'
    timestamp: datetime
    data: Dict[str, Any]


async def broadcast_update(update_type: str, data: Dict[str, Any]) -> None:
    """Helper to broadcast an update to all connected clients."""
    message = {
        "type": update_type,
        "timestamp": datetime.now(timezone.utc),
        "data": data,
    }
    await manager.broadcast(message)
