# WebSocket Real-Time Updates

Aether-V now includes WebSocket support for real-time updates, providing a smoother frontend experience without the need to constantly poll the REST API.

## Overview

The WebSocket implementation augments (not replaces) the REST API, providing real-time push notifications for events like:
- New notifications created
- Notification state changes (read/unread)
- Future: Inventory updates, job status changes, etc.

## Architecture

### Backend Components

1. **WebSocket Service** (`app/services/websocket_service.py`)
   - Manages WebSocket connections
   - Handles client subscriptions to topics
   - Broadcasts messages to subscribed clients
   - Automatic cleanup of disconnected clients

2. **WebSocket Endpoint** (`/ws`)
   - Accepts WebSocket connections
   - Sends initial state on connection
   - Handles client messages (subscribe, unsubscribe, ping)

3. **Notification Service Integration**
   - Automatically broadcasts new notifications via WebSocket
   - Broadcasts notification updates (e.g., mark as read)

### Frontend Components

1. **WebSocket Client** (`static/websocket.js`)
   - Manages WebSocket connection lifecycle
   - Automatic reconnection with exponential backoff
   - Connection status tracking
   - Topic subscription management
   - Ping/pong keep-alive

2. **Main Application Integration** (`static/main.js`)
   - Handles WebSocket messages
   - Updates UI in real-time
   - Falls back to REST API when needed

## Features

### Automatic Reconnection

The WebSocket client automatically reconnects when the connection is lost:
- Exponential backoff strategy (1s → 1.5s → 2.25s → ... up to 30s)
- Up to 10 reconnection attempts
- Automatic resubscription to topics after reconnection

### Connection Status Indicators

Visual indicators on the notification bell icon show the connection state:
- 🟢 **Green pulse**: Connected and receiving live updates
- 🟠 **Orange pulse**: Connecting to server
- 🔴 **Red pulse**: Reconnecting after disconnection
- ⚫ **Gray**: Disconnected (max retries reached)

### Topic-Based Subscriptions

Clients can subscribe to specific topics:
- `notifications`: Notification updates
- `inventory`: Inventory changes (future)
- `jobs`: Job status updates (future)
- `all`: All updates

### Initial State

On connection, the server sends the complete current state:
```json
{
  "type": "initial_state",
  "data": {
    "notifications": [...],
    "unread_count": 3
  }
}
```

## Message Types

### Server → Client Messages

#### Connection Confirmation
```json
{
  "type": "connection",
  "status": "connected",
  "client_id": "uuid",
  "timestamp": "2024-01-01T00:00:00Z"
}
```

#### Initial State
```json
{
  "type": "initial_state",
  "data": {
    "notifications": [...]
  }
}
```

#### Notification Created
```json
{
  "type": "notification",
  "action": "created",
  "data": {
    "id": "uuid",
    "title": "...",
    "message": "...",
    "level": "info",
    "category": "system",
    "created_at": "...",
    "read": false
  }
}
```

#### Notification Updated
```json
{
  "type": "notification",
  "action": "updated",
  "data": {
    "id": "uuid",
    "read": true
  }
}
```

### Client → Server Messages

#### Subscribe to Topics
```json
{
  "type": "subscribe",
  "topics": ["notifications", "jobs"]
}
```

#### Unsubscribe from Topics
```json
{
  "type": "unsubscribe",
  "topics": ["notifications"]
}
```

#### Ping (Keep-Alive)
```json
{
  "type": "ping"
}
```

## Usage Example

### JavaScript Client

```javascript
// WebSocket client is automatically initialized on page load
// Access via global wsClient object

// Subscribe to additional topics
wsClient.subscribe(['jobs', 'inventory']);

// Listen for specific message types
wsClient.on('notification', (message) => {
  console.log('Notification update:', message);
  // Update UI accordingly
});

// Listen for connection status changes
wsClient.onConnectionStatus((status, data) => {
  console.log('Connection status:', status);
  if (status === 'connected') {
    console.log('WebSocket connected!');
  }
});

// Check connection status
if (wsClient.isConnected()) {
  console.log('Connected with client ID:', wsClient.getClientId());
}
```

### Backend Integration

```python
from app.services.websocket_service import websocket_manager
from app.services.notification_service import notification_service

# Broadcast a message to all clients subscribed to 'notifications'
await websocket_manager.broadcast({
    "type": "notification",
    "action": "created",
    "data": {...}
}, topic="notifications")

# Send a message to a specific client
await websocket_manager.send_personal_message(client_id, {
    "type": "custom",
    "data": {...}
})
```

## Configuration

No additional configuration is required. WebSocket support is enabled automatically when the server starts.

### Environment Variables

Standard server configuration applies:
- `DEBUG`: Enable debug logging (includes WebSocket events)
- `DUMMY_DATA`: Use dummy data for testing

## Testing

### Manual Testing

1. Open the web UI in a browser
2. Open browser DevTools → Console
3. Look for WebSocket connection logs:
   ```
   Connecting to WebSocket: ws://localhost:8000/ws
   WebSocket connected
   Received initial state: {...}
   ```
4. Check the notification bell icon for the connection status indicator
5. Create a test notification (via backend) and verify it appears instantly

### Automated Testing

```python
# Test WebSocket integration
import asyncio
from app.services.websocket_service import websocket_manager
from app.services.notification_service import notification_service

async def test():
    await notification_service.start()
    notification_service.set_websocket_manager(websocket_manager)
    
    notification = notification_service.create_notification(
        title="Test",
        message="Test message",
        level=NotificationLevel.INFO,
        category=NotificationCategory.SYSTEM
    )
    
    assert notification is not None
    print("✓ WebSocket integration test passed")

asyncio.run(test())
```

## Backward Compatibility

The REST API remains fully functional and is still used for:
- Initial page load data
- Fallback when WebSocket is unavailable
- External automation and integrations

WebSocket enhances the user experience but is not required for basic functionality.

## Future Enhancements

Planned features:
- Inventory change notifications
- Job status updates in real-time
- VM state change notifications
- Batch updates for better performance
- Message compression for large datasets
- Authentication token validation for WebSocket connections

## Troubleshooting

### WebSocket Won't Connect

1. Check browser console for error messages
2. Verify server is running and accessible
3. Check for proxy/load balancer WebSocket support
4. Ensure no firewall blocking WebSocket connections

### Frequent Disconnections

1. Check network stability
2. Verify proxy/load balancer timeout settings
3. Increase ping interval if needed
4. Check server logs for errors

### Messages Not Received

1. Verify subscription to correct topics
2. Check browser console for WebSocket errors
3. Verify server-side broadcast implementation
4. Check client_id is correct

## Security Considerations

⚠️ **IMPORTANT**: The current WebSocket implementation does not include authentication.

### Development vs Production

**Development Mode**:
- WebSocket connections are accepted without authentication
- Suitable for development and testing environments
- Should only be used behind a secure network/firewall

**Production Recommendations**:

1. **Add Authentication**: Before deploying to production, implement token-based authentication:
   ```python
   # Example: Validate token on WebSocket connection
   @router.websocket("/ws")
   async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
       # Validate token before accepting connection
       user = await validate_token(token)
       if not user:
           await websocket.close(code=1008, reason="Unauthorized")
           return
       # ... rest of connection handling
   ```

2. **Use WSS (WebSocket Secure)**: Always use encrypted WebSocket connections in production
   - Configure ingress/load balancer for TLS termination
   - Use `wss://` protocol instead of `ws://`

3. **Implement Rate Limiting**: Protect against abuse
   ```python
   # Add rate limiting per client_id
   rate_limiter.check_rate(client_id)
   ```

4. **Validate Client Messages**: Always validate and sanitize client input
   ```python
   # Current implementation validates message types
   # Add additional validation as needed
   ```

5. **Monitor Connections**: Track active connections and implement limits
   ```python
   # Set max connections per user/IP
   if len(connections_per_ip[ip]) > MAX_CONNECTIONS:
       await websocket.close(code=1008, reason="Too many connections")
   ```

### Current Security Measures

- Message validation on server side
- Automatic cleanup of stale connections
- No sensitive data in WebSocket messages (notifications are already visible in REST API)
- Session-based authentication still required for REST API endpoints

### Security Roadmap

Priority security enhancements:
1. ⚠️ **HIGH PRIORITY**: Add authentication token validation for WebSocket connections
2. Add per-client rate limiting
3. Implement connection limits per user
4. Add audit logging for WebSocket events
5. Implement message encryption for sensitive data
