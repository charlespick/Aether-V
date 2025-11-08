"""WebSocket service for real-time updates."""
import logging
import json
import asyncio
from typing import Dict, Set, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        # client_id -> set of topics
        self.subscriptions: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """Accept and register a new WebSocket connection."""
        try:
            await websocket.accept()
            async with self._lock:
                self.active_connections[client_id] = websocket
                self.subscriptions[client_id] = set()
            logger.info(f"WebSocket client connected: {client_id}")

            # Send welcome message
            await self.send_personal_message(client_id, {
                "type": "connection",
                "status": "connected",
                "client_id": client_id,
                "timestamp": datetime.utcnow().isoformat()
            })
            return True
        except Exception as e:
            logger.error(
                f"Error connecting WebSocket client {client_id} [{type(e).__name__}]: {e}")
            return False

    async def disconnect(self, client_id: str):
        """Remove a WebSocket connection."""
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            if client_id in self.subscriptions:
                del self.subscriptions[client_id]
        logger.info(f"WebSocket client disconnected: {client_id}")

    async def subscribe(self, client_id: str, topics: list):
        """Subscribe a client to specific topics."""
        async with self._lock:
            if client_id in self.subscriptions:
                self.subscriptions[client_id].update(topics)
                logger.debug(f"Client {client_id} subscribed to: {topics}")

    async def unsubscribe(self, client_id: str, topics: list):
        """Unsubscribe a client from specific topics."""
        async with self._lock:
            if client_id in self.subscriptions:
                self.subscriptions[client_id].difference_update(topics)
                logger.debug(f"Client {client_id} unsubscribed from: {topics}")

    async def send_personal_message(self, client_id: str, message: dict):
        """Send a message to a specific client."""
        websocket = self.active_connections.get(client_id)
        if websocket:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")
                await self.disconnect(client_id)

    async def broadcast(self, message: dict, topic: Optional[str] = None):
        """Broadcast a message to all connected clients or clients subscribed to a topic."""
        disconnected_clients = []

        async with self._lock:
            clients_to_send = []

            if topic:
                # Send only to clients subscribed to this topic
                for client_id, topics in self.subscriptions.items():
                    if topic in topics or "all" in topics:
                        clients_to_send.append(client_id)
            else:
                # Send to all clients
                clients_to_send = list(self.active_connections.keys())

            # Send messages outside the lock to avoid blocking
            for client_id in clients_to_send:
                websocket = self.active_connections.get(client_id)
                if websocket:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Error broadcasting to {client_id}: {e}")
                        disconnected_clients.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected_clients:
            await self.disconnect(client_id)

    async def get_connection_count(self) -> int:
        """Get the number of active connections."""
        async with self._lock:
            return len(self.active_connections)

    async def handle_client_message(self, client_id: str, message: dict):
        """Handle incoming messages from clients with validation."""
        # Validate message structure
        if not isinstance(message, dict):
            logger.warning(
                f"Invalid message type from client {client_id}: {type(message)}")
            return

        message_type = message.get("type")
        if not message_type or not isinstance(message_type, str):
            logger.warning(
                f"Invalid or missing message type from client {client_id}")
            return

        # Rate limiting could be added here by tracking message counts per client

        if message_type == "subscribe":
            topics = message.get("topics", [])
            await self.subscribe(client_id, topics)
            await self.send_personal_message(client_id, {
                "type": "subscription",
                "status": "subscribed",
                "topics": topics
            })

        elif message_type == "unsubscribe":
            topics = message.get("topics", [])
            await self.unsubscribe(client_id, topics)
            await self.send_personal_message(client_id, {
                "type": "subscription",
                "status": "unsubscribed",
                "topics": topics
            })

        elif message_type == "ping":
            await self.send_personal_message(client_id, {
                "type": "pong",
                "timestamp": datetime.utcnow().isoformat()
            })


# Global WebSocket connection manager
websocket_manager = ConnectionManager()
