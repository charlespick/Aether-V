// WebSocket client for real-time updates
class WebSocketClient {
    constructor() {
        this.ws = null;
        this.clientId = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
        this.reconnectTimer = null;
        this.pingInterval = null;
        this.messageHandlers = new Map();
        this.connectionStatusCallbacks = [];
        this.subscriptions = new Set();
        this.wsToken = null; // Store WebSocket token
    }

    async connect() {
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            console.log('WebSocket already connected or connecting');
            return;
        }

        // Get WebSocket token if authentication is enabled
        try {
            await this.fetchWebSocketToken();
        } catch (error) {
            console.error('Failed to get WebSocket token:', error);
            this.updateConnectionStatus('error');
            this.scheduleReconnect();
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        let wsUrl = `${protocol}//${window.location.host}/ws`;
        
        // Add token to URL if we have one
        if (this.wsToken) {
            wsUrl += `?token=${encodeURIComponent(this.wsToken)}`;
        }
        
        console.log('Connecting to WebSocket:', wsUrl.replace(/token=[^&]+/, 'token=***'));
        this.updateConnectionStatus('connecting');

        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.reconnectDelay = 1000;
                this.updateConnectionStatus('connected');
                
                // Start ping interval to keep connection alive
                this.startPingInterval();
                
                // Resubscribe to topics if we have any
                if (this.subscriptions.size > 0) {
                    this.subscribe(Array.from(this.subscriptions));
                }
            };

            this.ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('error');
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket disconnected', event.code, event.reason);
                this.connected = false;
                this.stopPingInterval();
                
                // Check if this was an authentication failure (code 1008)
                if (event.code === 1008) {
                    console.error('WebSocket authentication failed');
                    this.updateConnectionStatus('auth_failed');
                    // Clear the token and try to reconnect (will fetch a new token)
                    this.wsToken = null;
                } else {
                    this.updateConnectionStatus('disconnected');
                }
                
                // Attempt to reconnect
                this.scheduleReconnect();
            };
        } catch (error) {
            console.error('Error creating WebSocket:', error);
            this.updateConnectionStatus('error');
            this.scheduleReconnect();
        }
    }

    disconnect() {
        console.log('Manually disconnecting WebSocket');
        this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.stopPingInterval();
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connected = false;
        this.updateConnectionStatus('disconnected');
    }

    scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('Max reconnect attempts reached');
            this.updateConnectionStatus('failed');
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1), this.maxReconnectDelay);
        
        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        this.updateConnectionStatus('reconnecting', { attempt: this.reconnectAttempts, delay });

        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, delay);
    }

    startPingInterval() {
        this.stopPingInterval();
        // Send ping every 30 seconds to keep connection alive
        this.pingInterval = setInterval(() => {
            if (this.connected) {
                this.send({ type: 'ping' });
            }
        }, 30000);
    }

    stopPingInterval() {
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
            return true;
        } else {
            console.warn('WebSocket not connected, cannot send message');
            return false;
        }
    }

    subscribe(topics) {
        if (!Array.isArray(topics)) {
            topics = [topics];
        }
        
        topics.forEach(topic => this.subscriptions.add(topic));
        
        if (this.connected) {
            this.send({
                type: 'subscribe',
                topics: topics
            });
        }
    }

    unsubscribe(topics) {
        if (!Array.isArray(topics)) {
            topics = [topics];
        }
        
        topics.forEach(topic => this.subscriptions.delete(topic));
        
        if (this.connected) {
            this.send({
                type: 'unsubscribe',
                topics: topics
            });
        }
    }

    on(messageType, handler) {
        if (!this.messageHandlers.has(messageType)) {
            this.messageHandlers.set(messageType, []);
        }
        this.messageHandlers.get(messageType).push(handler);
    }

    off(messageType, handler) {
        if (this.messageHandlers.has(messageType)) {
            const handlers = this.messageHandlers.get(messageType);
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
            }
        }
    }

    onConnectionStatus(callback) {
        this.connectionStatusCallbacks.push(callback);
    }

    updateConnectionStatus(status, data = {}) {
        this.connectionStatusCallbacks.forEach(callback => {
            try {
                callback(status, data);
            } catch (error) {
                console.error('Error in connection status callback:', error);
            }
        });
    }

    handleMessage(message) {
        const messageType = message.type;
        
        // Handle special message types
        if (messageType === 'connection') {
            this.clientId = message.client_id;
            console.log('Received client ID:', this.clientId);
        } else if (messageType === 'initial_state') {
            console.log('Received initial state:', message.data);
        } else if (messageType === 'pong') {
            // Ping response, connection is alive
            console.debug('Received pong');
        }
        
        // Call registered handlers
        if (this.messageHandlers.has(messageType)) {
            const handlers = this.messageHandlers.get(messageType);
            handlers.forEach(handler => {
                try {
                    handler(message);
                } catch (error) {
                    console.error(`Error in ${messageType} handler:`, error);
                }
            });
        }
    }

    isConnected() {
        return this.connected;
    }

    getClientId() {
        return this.clientId;
    }

    async fetchWebSocketToken() {
        /**
         * Fetch a WebSocket authentication token from the server.
         * This token is used to authenticate the WebSocket connection.
         */
        try {
            const response = await fetch('/auth/ws-token', {
                method: 'GET',
                credentials: 'same-origin' // Include session cookies
            });
            
            if (response.ok) {
                const data = await response.json();
                this.wsToken = data.token;
                console.log('WebSocket token obtained successfully');
                return true;
            } else if (response.status === 401) {
                // Not authenticated - this is OK for dev mode
                console.log('No authentication token available (dev mode or not logged in)');
                this.wsToken = null;
                return true;
            } else {
                console.error('Failed to get WebSocket token:', response.status);
                return false;
            }
        } catch (error) {
            console.error('Error fetching WebSocket token:', error);
            // In dev mode, we can still connect without a token
            this.wsToken = null;
            return true;
        }
    }
}

// Create global WebSocket client instance
const wsClient = new WebSocketClient();

// Auto-connect when page loads
document.addEventListener('DOMContentLoaded', () => {
    wsClient.connect();
});

// Reconnect when page becomes visible (tab switching)
document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !wsClient.isConnected()) {
        console.log('Page became visible, reconnecting WebSocket');
        wsClient.connect();
    }
});
