/**
 * useAsyncData Composable
 * 
 * Provides a reusable pattern for non-blocking data fetching with loading and error states.
 * This composable handles the complete data lifecycle:
 * - Loading state management
 * - Error handling
 * - Data caching (optional)
 * - Automatic retries (optional)
 * 
 * Usage:
 * ```typescript
 * const hostsData = useAsyncData(
 *   async () => {
 *     const response = await apiClient.get('/api/hosts');
 *     return response.data;
 *   },
 *   { cache: true, cacheKey: 'hosts' }
 * );
 * 
 * // In template:
 * {#if $hostsData.loading}
 *   <Spinner />
 * {:else if $hostsData.error}
 *   <Error message={$hostsData.error} />
 * {:else}
 *   <HostList data={$hostsData.data} />
 * {/if}
 * ```
 */

import { writable, derived, type Readable } from 'svelte/store';

type FetchFunction<T> = () => Promise<T>;

interface AsyncDataOptions {
    /** Enable caching of the result */
    cache?: boolean;
    /** Cache key for storing/retrieving data */
    cacheKey?: string;
    /** Cache TTL in milliseconds */
    cacheTTL?: number;
    /** Automatically refetch on mount */
    refetchOnMount?: boolean;
    /** Retry failed requests */
    retry?: boolean;
    /** Number of retry attempts */
    retryAttempts?: number;
    /** Delay between retries in ms */
    retryDelay?: number;
}

interface AsyncDataState<T> {
    data: T | null;
    loading: boolean;
    error: string | null;
    timestamp: number | null;
}

interface AsyncDataReturn<T> {
    subscribe: Readable<AsyncDataState<T>>['subscribe'];
    data: Readable<T | null>;
    loading: Readable<boolean>;
    error: Readable<string | null>;
    timestamp: Readable<number | null>;
    execute: () => Promise<void>;
    refresh: () => Promise<void>;
    reset: () => void;
    clearCache: () => void;
}

// Global cache for storing fetched data
const dataCache = new Map<string, { data: unknown; timestamp: number }>();

/**
 * Create an async data fetcher with reactive loading/error states.
 */
export function useAsyncData<T>(
    fetchFn: FetchFunction<T>,
    options: AsyncDataOptions = {}
): AsyncDataReturn<T> {
    const {
        cache = false,
        cacheKey = '',
        cacheTTL = 60000, // 1 minute default
        refetchOnMount = true,
        retry = false,
        retryAttempts = 3,
        retryDelay = 1000
    } = options;

    // Reactive state using writable store
    const state = writable<AsyncDataState<T>>({
        data: null,
        loading: false,
        error: null,
        timestamp: null
    });

    /**
     * Check if cached data is still valid.
     */
    function isCacheValid(): boolean {
        if (!cache || !cacheKey) return false;

        const cached = dataCache.get(cacheKey);
        if (!cached) return false;

        const age = Date.now() - cached.timestamp;
        return age < cacheTTL;
    }

    /**
     * Get data from cache.
     */
    function getFromCache(): T | null {
        if (!cache || !cacheKey) return null;

        const cached = dataCache.get(cacheKey);
        if (!cached) return null;

        return cached.data as T;
    }

    /**
     * Save data to cache.
     */
    function saveToCache(data: T) {
        if (!cache || !cacheKey) return;

        dataCache.set(cacheKey, {
            data,
            timestamp: Date.now()
        });
    }

    /**
     * Fetch data with retry logic.
     */
    async function fetchWithRetry(attempt: number = 1): Promise<T> {
        try {
            return await fetchFn();
        } catch (error) {
            if (retry && attempt < retryAttempts) {
                console.log(`useAsyncData: Retry attempt ${attempt}/${retryAttempts}`);
                await new Promise(resolve => setTimeout(resolve, retryDelay));
                return fetchWithRetry(attempt + 1);
            }
            throw error;
        }
    }

    /**
     * Execute the fetch operation.
     */
    async function execute() {
        // Check cache first
        if (isCacheValid()) {
            const cached = getFromCache();
            if (cached !== null) {
                console.log('useAsyncData: Using cached data', cacheKey);
                state.update($s => ({
                    ...$s,
                    data: cached,
                    loading: false,
                    error: null
                }));
                return;
            }
        }

        // Start loading
        state.update($s => ({ ...$s, loading: true, error: null }));

        try {
            const result = await fetchWithRetry();

            state.update($s => ({
                ...$s,
                data: result,
                timestamp: Date.now(),
                error: null,
                loading: false
            }));

            // Cache the result
            saveToCache(result);

            console.log('useAsyncData: Fetch successful', cacheKey || 'no cache key');

        } catch (error) {
            console.error('useAsyncData: Fetch failed', error);
            console.error('useAsyncData: Error type:', typeof error);
            console.error('useAsyncData: Error instanceof Error:', error instanceof Error);

            // Properly serialize error to string
            let errorMessage: string;
            if (error instanceof Error) {
                errorMessage = error.message;
            } else if (typeof error === 'string') {
                errorMessage = error;
            } else if (error && typeof error === 'object') {
                try {
                    errorMessage = JSON.stringify(error);
                } catch (stringifyError) {
                    errorMessage = String(error);
                }
            } else {
                errorMessage = 'Failed to fetch data';
            }

            state.update($s => ({
                ...$s,
                error: errorMessage,
                data: null,
                loading: false
            }));
        }
    }

    /**
     * Refresh data (bypass cache).
     */
    async function refresh() {
        // Clear cache for this key
        if (cache && cacheKey) {
            dataCache.delete(cacheKey);
        }

        await execute();
    }

    /**
     * Reset state to initial values.
     */
    function reset() {
        state.set({
            data: null,
            loading: false,
            error: null,
            timestamp: null
        });
    }

    /**
     * Clear cached data.
     */
    function clearCache() {
        if (cache && cacheKey) {
            dataCache.delete(cacheKey);
        }
    }

    // Auto-fetch on mount if enabled
    if (refetchOnMount) {
        execute();
    }

    // Return reactive store and control methods
    return {
        // Store subscription (allows $asyncData syntax in components)
        subscribe: state.subscribe,

        // Derived stores for individual properties
        data: derived(state, $s => $s.data),
        loading: derived(state, $s => $s.loading),
        error: derived(state, $s => $s.error),
        timestamp: derived(state, $s => $s.timestamp),

        // Control methods
        execute,
        refresh,
        reset,
        clearCache
    };
}

/**
 * Clear all cached data.
 */
export function clearAllCache() {
    dataCache.clear();
    console.log('useAsyncData: All cache cleared');
}

/**
 * Clear cached data by key.
 */
export function clearCacheByKey(key: string) {
    dataCache.delete(key);
    console.log('useAsyncData: Cache cleared for key', key);
}
