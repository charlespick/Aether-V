/**
 * Global Application Loading Store
 * 
 * Manages the overall application initialization state using Svelte writable stores.
 * Controls the fullscreen loading spinner shown during app bootstrap.
 * 
 * Initialization phases:
 * - initializing: App just started
 * - auth: Validating session and authentication  
 * - websocket: Establishing WebSocket connection (BLOCKING - must complete before app ready)
 * - metadata: Loading initial configuration/metadata
 * - ready: All initialization complete, app ready to use
 * - error: Initialization failed
 */

import { writable, derived } from 'svelte/store';
import { apiClient } from '$lib/services/apiClient';
import { websocketClient } from '$lib/services/websocketClient';

type LoadingPhase = 'initializing' | 'auth' | 'websocket' | 'metadata' | 'ready' | 'error';

interface LoadingState {
    phase: LoadingPhase;
    progress: number;
    message: string;
    error?: string;
}

const state = writable<LoadingState>({
    phase: 'initializing',
    progress: 0,
    message: 'Initializing application...'
});

let initializationStarted = false;

class AppLoadingStore {
    // Store subscription
    subscribe = state.subscribe;

    // Derived stores for reactive access
    phase = derived(state, $s => $s.phase);
    progress = derived(state, $s => $s.progress);
    message = derived(state, $s => $s.message);
    error = derived(state, $s => $s.error);
    isReady = derived(state, $s => $s.phase === 'ready');
    hasError = derived(state, $s => $s.phase === 'error');
    isLoading = derived(state, $s => $s.phase !== 'ready' && $s.phase !== 'error');

    async initialize() {
        if (initializationStarted) {
            console.warn('AppLoadingStore: Already initialized');
            return;
        }

        initializationStarted = true;
        console.log('AppLoadingStore: Starting initialization sequence');

        try {
            // Phase 1: Validate session
            this.updatePhase('auth', 20, 'Validating session...');
            await this.validateSession();

            // Phase 2: Connect WebSocket (BLOCKING requirement per user spec)
            this.updatePhase('websocket', 40, 'Connecting to server...');
            await this.connectWebSocket();

            // Phase 3: Load metadata
            this.updatePhase('metadata', 70, 'Loading configuration...');
            await this.loadMetadata();

            // Phase 4: Ready
            this.updatePhase('ready', 100, 'Ready');
            console.log('AppLoadingStore: Initialization complete');

        } catch (error) {
            console.error('AppLoadingStore: Initialization failed', error);
            state.update($s => ({
                ...$s,
                phase: 'error',
                error: error instanceof Error ? error.message : 'Initialization failed',
                message: 'Initialization failed'
            }));
        }
    }

    private updatePhase(phase: LoadingPhase, progress: number, message: string) {
        state.update($s => ({ ...$s, phase, progress, message, error: undefined }));
    }

    private async validateSession() {
        const response = await apiClient.get('/api/v1/about');
        if (!response.ok && response.status === 401) {
            throw new Error('Not authenticated');
        }
        console.log('AppLoadingStore: Session validated');
    }

    private async connectWebSocket() {
        await websocketClient.connect();

        // WebSocket connect() already throws on failure, so if we get here, connection succeeded
        console.log('AppLoadingStore: WebSocket connected');
    }

    private async loadMetadata() {
        // Placeholder for loading initial metadata
        await new Promise(resolve => setTimeout(resolve, 500));
        console.log('AppLoadingStore: Metadata loaded');
    }

    retry() {
        initializationStarted = false;
        state.set({
            phase: 'initializing',
            progress: 0,
            message: 'Initializing application...'
        });
        this.initialize();
    }
}

export const appLoading = new AppLoadingStore();
