/**
 * WebSocket Client Service
 * 
 * Manages the persistent WebSocket connection to the server for real-time updates.
 * This service handles:
 * - Connection establishment with automatic reconnection
 * - Message routing to subscribers
 * - Connection state management
 * - Heartbeat/ping-pong for connection health
 * 
 * The WebSocket connection is required before the app becomes "ready" to ensure
 * users always see fresh, real-time data from the moment the UI appears.
 */

import { writable, derived, get } from 'svelte/store';
import { toastStore } from '$lib/stores/toastStore';

type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting' | 'error';

interface WebSocketMessage {
    type: string;
    data: unknown;
    timestamp?: string;
}

type MessageHandler = (message: WebSocketMessage) => void;

interface WebSocketState {
    connectionState: ConnectionState;
    reconnectAttempts: number;
    lastError?: string;
}

const state = writable<WebSocketState>({
    connectionState: 'disconnected',
    reconnectAttempts: 0
});

class WebSocketClient {
    private socket: WebSocket | null = null;
    private reconnectTimer: number | null = null;
    private heartbeatTimer: number | null = null;
    private messageHandlers = new Map<string, Set<MessageHandler>>();

    // Configuration
    private readonly MAX_RECONNECT_ATTEMPTS = 5;
    private readonly RECONNECT_DELAY = 3000; // 3 seconds
    private readonly HEARTBEAT_INTERVAL = 30000; // 30 seconds

    // Reactive getters using derived stores
    get connectionState() {
        return derived(state, $s => $s.connectionState);
    }

    get isConnected() {
        return derived(state, $s => $s.connectionState === 'connected');
    }

    get isDisconnected() {
        return derived(state, $s => $s.connectionState === 'disconnected' || $s.connectionState === 'error');
    }

    get reconnectAttempts() {
        return derived(state, $s => $s.reconnectAttempts);
    }

    /**
     * Establish WebSocket connection to the server.
     * Returns a promise that resolves when connected, rejects on failure.
     */
    async connect(): Promise<void> {
        if (this.socket?.readyState === WebSocket.OPEN) {
            console.log('WebSocket: Already connected');
            return Promise.resolve();
        }

        if (this.socket?.readyState === WebSocket.CONNECTING) {
            console.log('WebSocket: Connection already in progress');
            return this.waitForConnection();
        }

        console.log('WebSocket: Initiating connection');
        state.update($s => ({ ...$s, connectionState: 'connecting' }));

        return new Promise((resolve, reject) => {
            try {
                // Construct WebSocket URL
                // In production, use wss:// with current host
                // Session cookie will be sent automatically for authentication
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${window.location.host}/ws`;

                console.log(`WebSocket: Connecting to ${wsUrl}`);
                this.socket = new WebSocket(wsUrl);

                // Connection opened
                this.socket.onopen = () => {
                    console.log('WebSocket: Connection established');
                    state.update($s => ({ ...$s, connectionState: 'connected', reconnectAttempts: 0, lastError: undefined }));
                    this.startHeartbeat();
                    resolve();
                };

                // Message received
                this.socket.onmessage = (event) => {
                    this.handleMessage(event.data);
                };

                // Connection closed
                this.socket.onclose = (event) => {
                    console.log(`WebSocket: Connection closed (code: ${event.code}, reason: ${event.reason})`);
                    this.cleanup();

                    // Only attempt reconnection if we were previously connected
                    // (not during initial connection attempt)
                    if (get(state).connectionState === 'connected') {
                        this.attemptReconnect();
                    } else {
                        state.update($s => ({ ...$s, connectionState: 'disconnected' }));
                        reject(new Error('WebSocket connection failed'));
                    }
                };

                // Connection error
                this.socket.onerror = (error) => {
                    console.error('WebSocket: Connection error', error);
                    state.update($s => ({ ...$s, lastError: 'WebSocket connection error' }));

                    // Error during initial connection
                    if (get(state).connectionState === 'connecting') {
                        state.update($s => ({ ...$s, connectionState: 'error' }));
                        reject(new Error('Failed to establish WebSocket connection'));
                    }
                };

            } catch (error) {
                console.error('WebSocket: Failed to create connection', error);
                state.update($s => ({
                    ...$s,
                    connectionState: 'error',
                    lastError: error instanceof Error ? error.message : 'Unknown error'
                }));
                reject(error);
            }
        });
    }

    /**
     * Wait for an existing connection attempt to complete.
     */
    private waitForConnection(): Promise<void> {
        return new Promise((resolve, reject) => {
            const checkInterval = setInterval(() => {
                if (this.socket?.readyState === WebSocket.OPEN) {
                    clearInterval(checkInterval);
                    resolve();
                } else if (get(state).connectionState === 'error' || get(state).connectionState === 'disconnected') {
                    clearInterval(checkInterval);
                    reject(new Error('Connection failed'));
                }
            }, 100);

            // Timeout after 10 seconds
            setTimeout(() => {
                clearInterval(checkInterval);
                reject(new Error('Connection timeout'));
            }, 10000);
        });
    }

    /**
     * Attempt to reconnect after connection loss.
     */
    private attemptReconnect() {
        if (this.reconnectTimer !== null) {
            return; // Already attempting reconnection
        }

        if (get(state).reconnectAttempts >= this.MAX_RECONNECT_ATTEMPTS) {
            console.error('WebSocket: Max reconnection attempts reached');
            state.update($s => ({
                ...$s,
                connectionState: 'error',
                lastError: 'Failed to reconnect to server'
            }));

            // Show disconnected status with retry button (no countdown)
            toastStore.connectionStatus('disconnected', undefined, () => {
                // Retry button callback
                state.update($s => ({ ...$s, reconnectAttempts: 0 }));
                this.attemptReconnect();
            });
            return;
        }

        state.update($s => ({
            ...$s,
            connectionState: 'reconnecting',
            reconnectAttempts: $s.reconnectAttempts + 1
        }));

        console.log(`WebSocket: Reconnection attempt ${get(state).reconnectAttempts}/${this.MAX_RECONNECT_ATTEMPTS}`);

        // Show reconnecting status with countdown
        const countdownSeconds = Math.ceil(this.RECONNECT_DELAY / 1000);
        const toastId = toastStore.connectionStatus('reconnecting', countdownSeconds);

        this.reconnectTimer = window.setTimeout(() => {
            this.reconnectTimer = null;
            this.connect()
                .then(() => {
                    // Connection restored - remove reconnecting toast and show success
                    toastStore.remove(toastId);
                    toastStore.connectionStatus('connected');
                })
                .catch(() => {
                    // If reconnection fails, try again
                    toastStore.remove(toastId);
                    this.attemptReconnect();
                });
        }, this.RECONNECT_DELAY);
    }

    /**
     * Send a message to the server.
     */
    send(type: string, data: unknown) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            console.warn('WebSocket: Cannot send message, not connected');
            return false;
        }

        const message: WebSocketMessage = {
            type,
            data,
            timestamp: new Date().toISOString()
        };

        try {
            this.socket.send(JSON.stringify(message));
            return true;
        } catch (error) {
            console.error('WebSocket: Failed to send message', error);
            return false;
        }
    }

    /**
     * Subscribe to messages of a specific type.
     * Returns an unsubscribe function.
     */
    subscribe(messageType: string, handler: MessageHandler): () => void {
        if (!this.messageHandlers.has(messageType)) {
            this.messageHandlers.set(messageType, new Set());
        }

        this.messageHandlers.get(messageType)!.add(handler);

        // Return unsubscribe function
        return () => {
            const handlers = this.messageHandlers.get(messageType);
            if (handlers) {
                handlers.delete(handler);
                if (handlers.size === 0) {
                    this.messageHandlers.delete(messageType);
                }
            }
        };
    }

    /**
     * Handle incoming WebSocket message.
     */
    private handleMessage(rawData: string) {
        try {
            const message: WebSocketMessage = JSON.parse(rawData);

            // Handle ping/pong for heartbeat
            if (message.type === 'ping') {
                this.send('pong', {});
                return;
            }

            // Route message to subscribed handlers
            const handlers = this.messageHandlers.get(message.type);
            if (handlers && handlers.size > 0) {
                handlers.forEach(handler => {
                    try {
                        handler(message);
                    } catch (error) {
                        console.error(`WebSocket: Error in message handler for type "${message.type}"`, error);
                    }
                });
            } else {
                console.debug(`WebSocket: No handlers for message type "${message.type}"`);
            }

        } catch (error) {
            console.error('WebSocket: Failed to parse message', error, rawData);
        }
    }

    /**
     * Start heartbeat to keep connection alive.
     */
    private startHeartbeat() {
        this.stopHeartbeat();

        this.heartbeatTimer = window.setInterval(() => {
            if (this.socket?.readyState === WebSocket.OPEN) {
                this.send('ping', {});
            }
        }, this.HEARTBEAT_INTERVAL);
    }

    /**
     * Stop heartbeat timer.
     */
    private stopHeartbeat() {
        if (this.heartbeatTimer !== null) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    /**
     * Clean up connection resources.
     */
    private cleanup() {
        this.stopHeartbeat();

        if (this.socket) {
            this.socket.onopen = null;
            this.socket.onmessage = null;
            this.socket.onclose = null;
            this.socket.onerror = null;
            this.socket = null;
        }
    }

    /**
     * Disconnect from the server.
     */
    disconnect() {
        console.log('WebSocket: Disconnecting');

        if (this.reconnectTimer !== null) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        this.cleanup();
        get(state).connectionState = 'disconnected';
        get(state).reconnectAttempts = 0;
    }
}

// Export singleton instance
export const websocketClient = new WebSocketClient();
