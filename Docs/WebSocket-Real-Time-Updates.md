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

### Authentication Implementation

The WebSocket implementation now includes **full authentication support** matching the REST API security model:

**Supported Authentication Methods**:
1. ✅ **WebSocket-specific tokens** - Short-lived JWT tokens (5 minute expiry) obtained from `/auth/ws-token`
2. ✅ **OIDC JWT tokens** - Direct OIDC bearer tokens for API access
3. ✅ **Static API token** - For automation and service accounts
4. ✅ **Development mode** - Requires explicit `ALLOW_DEV_AUTH=true` flag

**Authentication Flow**:
1. Frontend requests a WebSocket token from `/auth/ws-token` using session credentials
2. Server validates the session and issues a short-lived JWT token
3. Frontend connects to WebSocket with token as query parameter: `/ws?token=xxx`
4. Server validates token before accepting connection
5. Invalid or missing tokens result in connection rejection (code 1008)

### Development vs Production

**Development Mode** (AUTH_ENABLED=false, ALLOW_DEV_AUTH=true):
- WebSocket connections allowed without authentication
- Suitable for local development and testing
- Should only be used behind secure networks

**Production Mode** (AUTH_ENABLED=true):
- ✅ All WebSocket connections require valid authentication
- ✅ Supports OIDC JWT tokens for interactive users
- ✅ Supports static API tokens for automation
- ✅ Short-lived WebSocket tokens for browser clients
- ✅ Role-based access control (respects `OIDC_ROLE_NAME`)

### Security Features

1. **Token Expiration**: WebSocket tokens expire after 5 minutes
2. **Automatic Token Refresh**: Frontend automatically fetches new tokens on reconnection
3. **Role Validation**: Tokens are checked for required roles before connection
4. **Audit Logging**: All authentication attempts are logged with IP and user info
5. **Secure Protocol Support**: WSS (WebSocket Secure) automatically used with HTTPS

### WSS (WebSocket Secure) Support

The WebSocket client automatically uses WSS when the page is served over HTTPS:

```javascript
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/ws`;
```

**For Production Deployment**:
- Configure ingress/load balancer for TLS termination
- Application automatically detects HTTPS and uses WSS
- No additional configuration required

### Configuration

WebSocket authentication respects all existing authentication environment variables:
- `AUTH_ENABLED` - Enable/disable authentication
- `ALLOW_DEV_AUTH` - Explicitly allow development mode
- `OIDC_ISSUER_URL` - OIDC provider URL
- `OIDC_CLIENT_ID` - OIDC client ID
- `OIDC_CLIENT_SECRET` - OIDC client secret
- `OIDC_ROLE_NAME` - Required role for access
- `API_TOKEN` - Static token for automation
- `SESSION_SECRET_KEY` - Secret for signing WebSocket tokens

### Rate Limiting Recommendations

For production deployments, consider implementing:
1. **Connection limits** - Max connections per user/IP
2. **Message rate limiting** - Limit messages per second per connection
3. **Token rate limiting** - Limit token requests to prevent abuse

Example implementation location: `app/services/websocket_service.py`

### Monitoring and Audit

All WebSocket events are logged:
- Connection attempts (successful and failed)
- Authentication failures with reason
- User disconnections
- Message processing errors

Example log entries:
```
INFO - WebSocket authenticated for user john.doe from 192.168.1.100
WARNING - WebSocket authentication failed: invalid token from 192.168.1.200
INFO - Client abc123 (john.doe) disconnected
```
