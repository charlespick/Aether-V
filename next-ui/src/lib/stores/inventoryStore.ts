/**
 * Inventory Store
 * 
 * Centralized state management for infrastructure inventory data.
 * This store provides a single source of truth for inventory across the application,
 * eliminating duplicate API calls and WebSocket subscriptions.
 * 
 * Features:
 * - Single API fetch on initialization
 * - Single WebSocket subscription for real-time updates
 * - Shared state accessible by Sidebar and all views
 * - Reactive updates propagate automatically to all subscribers
 */

import { writable, derived, get } from 'svelte/store';
import { websocketClient } from '$lib/services/websocketClient';
import { apiClient } from '$lib/services/apiClient';

export interface VM {
    id: string;
    name: string;
    host: string;
    state: string;
    cpu_count?: number;
    cpu_cores?: number; // Some APIs use cpu_cores
    memory_mb?: number;
    memory_gb?: number; // Some APIs use memory_gb
    memory_startup_gb?: number; // For dynamic memory
    memory_min_gb?: number; // For dynamic memory
    memory_max_gb?: number; // For dynamic memory
    dynamic_memory_enabled?: boolean;
    ip_addresses?: string[];
    ip_address?: string; // Fallback for single IP
    notes?: string | string[];
    cluster?: string;
    clustered?: boolean;
    is_clustered?: boolean;
    vm_clustered?: boolean;
    os_name?: string;
    os_family?: string;
    generation?: number | string;
    version?: string;
    created_at?: string;
    disks?: Array<{
        id?: string;
        name?: string;
        type?: string;
        capacity?: string;
        size_gb?: number;
        size?: string;
        path?: string;
        location?: string;
    }>;
    networks?: Array<{
        id?: string;
        name?: string;
        adapter_name?: string;
        ip_addresses?: string[];
        ip_address?: string;
        network_name?: string;
        virtual_switch?: string;
        vlan?: string | number;
    }>;
}

export interface Host {
    hostname: string;
    cluster: string;
    connected: boolean;
    total_cpu_cores?: number;
    total_memory_gb?: number;
    version?: string;
    last_seen?: string;
}

export interface Cluster {
    name: string;
    connected_hosts: number;
}

export interface InventoryData {
    clusters: Cluster[];
    hosts: Host[];
    vms: VM[];
    disconnected_hosts: Host[];
    total_hosts: number;
    total_vms: number;
    total_clusters: number;
    disconnected_count: number;
    last_refresh?: string;
    environment_name?: string;
}

interface InventoryState {
    data: InventoryData | null;
    loading: boolean;
    error: string | null;
    lastUpdate: number | null;
}

const initialState: InventoryState = {
    data: null,
    loading: false,
    error: null,
    lastUpdate: null
};

const state = writable<InventoryState>(initialState);

class InventoryStore {
    private initialized = false;
    private wsSubscribed = false;

    // Subscribe to the store
    subscribe = state.subscribe;

    // Derived stores for convenient access
    data = derived(state, $s => $s.data);
    loading = derived(state, $s => $s.loading);
    error = derived(state, $s => $s.error);
    lastUpdate = derived(state, $s => $s.lastUpdate);

    // Computed values
    totalHosts = derived(state, $s => $s.data?.total_hosts ?? 0);
    totalVMs = derived(state, $s => $s.data?.total_vms ?? 0);
    totalClusters = derived(state, $s => $s.data?.total_clusters ?? 0);
    disconnectedCount = derived(state, $s => $s.data?.disconnected_count ?? 0);
    environmentName = derived(state, $s => $s.data?.environment_name ?? 'Production Environment');

    // Get running VMs count
    runningVMs = derived(state, $s =>
        $s.data?.vms.filter(vm => vm.state === 'Running').length ?? 0
    );

    // Get stopped/non-running VMs count
    stoppedVMs = derived(state, $s =>
        $s.data?.vms.filter(vm => vm.state !== 'Running').length ?? 0
    );

    // Get connected hosts count
    connectedHosts = derived(state, $s =>
        $s.data?.hosts.length ?? 0
    );

    /**
     * Initialize the inventory store.
     * Fetches initial data and sets up WebSocket subscription.
     */
    async initialize() {
        if (this.initialized) {
            console.log('InventoryStore: Already initialized');
            return;
        }

        console.log('InventoryStore: Initializing...');
        this.initialized = true;

        // Fetch initial data
        await this.fetch();

        // Subscribe to WebSocket updates
        this.subscribeToWebSocket();
    }

    /**
     * Fetch inventory data from the API.
     */
    async fetch() {
        state.update($s => ({ ...$s, loading: true, error: null }));

        try {
            const response = await apiClient.get<InventoryData>('/api/v1/inventory');

            if (!response.ok) {
                throw new Error(response.error || 'Failed to fetch inventory');
            }

            state.update($s => ({
                ...$s,
                data: response.data!,
                loading: false,
                error: null,
                lastUpdate: Date.now()
            }));

            console.log('InventoryStore: Fetch successful');

        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Unknown error';
            console.error('InventoryStore: Fetch failed', errorMessage);

            state.update($s => ({
                ...$s,
                loading: false,
                error: errorMessage
            }));
        }
    }

    /**
     * Subscribe to WebSocket inventory updates.
     */
    private subscribeToWebSocket() {
        if (this.wsSubscribed) {
            console.log('InventoryStore: Already subscribed to WebSocket');
            return;
        }

        console.log('InventoryStore: Subscribing to WebSocket inventory updates');
        this.wsSubscribed = true;

        websocketClient.subscribe('inventory_update', (message: any) => {
            if (message.data) {
                console.log('InventoryStore: Received inventory update via WebSocket');

                state.update($s => ({
                    ...$s,
                    data: message.data,
                    lastUpdate: Date.now()
                }));
            }
        });
    }

    /**
     * Manually refresh inventory data.
     */
    async refresh() {
        console.log('InventoryStore: Manual refresh triggered');
        await this.fetch();
    }

    /**
     * Reset the store to initial state.
     */
    reset() {
        console.log('InventoryStore: Resetting store');
        state.set(initialState);
        this.initialized = false;
        // Note: WebSocket subscription persists across resets
    }

    /**
     * Get current data synchronously.
     */
    getData(): InventoryData | null {
        return get(state).data;
    }
}

// Export singleton instance
export const inventoryStore = new InventoryStore();
