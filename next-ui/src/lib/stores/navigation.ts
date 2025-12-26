/**
 * Navigation Store
 * 
 * Manages route transitions and navigation state for instant UI responsiveness.
 * Provides optimistic route changes - the UI updates immediately when a user clicks
 * a navigation link, before any data is fetched. This creates a snappy, responsive feel.
 * 
 * The actual view content will show layout-mimicking skeletons while data loads.
 */

import { writable, derived } from 'svelte/store';
import { goto } from '$app/navigation';
import { base } from '$app/paths';

export type RouteType = 'overview' | 'host' | 'vm' | 'cluster' | 'disconnected' | 'settings';

export interface Route {
    path: string;
    type: RouteType;
    label: string;
    params?: Record<string, string>;
}

interface NavigationState {
    currentRoute: Route | null;
    previousRoute: Route | null;
    isTransitioning: boolean;
    transitionDirection: 'forward' | 'back' | null;
}

const state = writable<NavigationState>({
    currentRoute: null,
    previousRoute: null,
    isTransitioning: false,
    transitionDirection: null
});

class NavigationStore {
    // Store subscription
    subscribe = state.subscribe;

    // Reactive getters using derived stores
    currentRoute = derived(state, $s => $s.currentRoute);
    previousRoute = derived(state, $s => $s.previousRoute);
    isTransitioning = derived(state, $s => $s.isTransitioning);
    transitionDirection = derived(state, $s => $s.transitionDirection);

    /**
     * Navigate to a new route.
     * This triggers an instant UI transition before data loading begins.
     */
    async navigateTo(route: Route) {
        console.log('Navigation: Navigating to', route.path);

        // Determine transition direction (for animations)
        const direction = this.determineDirection(route);

        // Update state with new route and transition
        state.update($s => ({
            previousRoute: $s.currentRoute,
            currentRoute: route,
            isTransitioning: true,
            transitionDirection: direction
        }));

        // Perform SvelteKit navigation
        await goto(route.path);

        // End transition after a brief delay (for exit animations)
        setTimeout(() => {
            state.update($s => ({
                ...$s,
                isTransitioning: false,
                transitionDirection: null
            }));
        }, 150);
    }

    /**
     * Update current route based on SvelteKit page store.
     * This is called when the URL changes (browser back/forward, direct navigation).
     */
    updateFromPage(pathname: string) {
        const route = this.parsePathToRoute(pathname);

        state.update($s => {
            if (route && route.path !== $s.currentRoute?.path) {
                return {
                    ...$s,
                    previousRoute: $s.currentRoute,
                    currentRoute: route
                };
            }
            return $s;
        });
    }

    /**
     * Parse a pathname into a Route object.
     */
    private parsePathToRoute(pathname: string): Route | null {
        // Remove base path if present
        const path = pathname.startsWith(base) ? pathname.slice(base.length) || '/' : pathname;

        // Match route patterns
        if (path === '/') {
            return { path: '/', type: 'overview', label: 'Overview' };
        }

        if (path === '/disconnected-hosts') {
            return { path: '/disconnected-hosts', type: 'disconnected', label: 'Disconnected Hosts' };
        }

        if (path === '/settings') {
            return { path: '/settings', type: 'settings', label: 'Settings' };
        }

        // Cluster route: /cluster/:name
        const clusterMatch = path.match(/^\/cluster\/([^/]+)$/);
        if (clusterMatch) {
            const clusterName = decodeURIComponent(clusterMatch[1]);
            return {
                path,
                type: 'cluster',
                label: `Cluster ${clusterName}`,
                params: { clusterName }
            };
        }

        // Host route: /host/:hostname
        const hostMatch = path.match(/^\/host\/([^/]+)$/);
        if (hostMatch) {
            const hostname = decodeURIComponent(hostMatch[1]);
            return {
                path,
                type: 'host',
                label: `Host ${hostname}`,
                params: { hostname }
            };
        }

        // VM route: /virtual-machine/:id
        const vmMatch = path.match(/^\/virtual-machine\/([^/]+)$/);
        if (vmMatch) {
            const vmId = decodeURIComponent(vmMatch[1]);
            return {
                path,
                type: 'vm',
                label: `VM ${vmId}`,
                params: { vmId }
            };
        }

        // Unknown route
        console.warn('Navigation: Unknown route pattern:', path);
        return null;
    }

    /**
     * Determine transition direction based on route hierarchy.
     * This helps with animation choices (slide left vs right, etc).
     */
    private determineDirection(route: Route): 'forward' | 'back' {
        let direction: 'forward' | 'back' = 'forward';

        state.subscribe($s => {
            const current = $s.currentRoute;
            if (!current) {
                direction = 'forward';
                return;
            }

            // Define route hierarchy for transition direction
            const hierarchy: RouteType[] = ['overview', 'cluster', 'host', 'vm', 'disconnected', 'settings'];

            const currentIndex = hierarchy.indexOf(current.type);
            const newIndex = hierarchy.indexOf(route.type);

            direction = newIndex > currentIndex ? 'forward' : 'back';
        })(); // Immediately unsubscribe

        return direction;
    }

    /**
     * Get route for a specific entity.
     * Helper method for generating routes programmatically.
     */
    getRoute(type: RouteType, params?: Record<string, string>): Route {
        switch (type) {
            case 'overview':
                return { path: '/', type: 'overview', label: 'Overview' };

            case 'cluster':
                const clusterName = params?.clusterName || '';
                return {
                    path: `/cluster/${encodeURIComponent(clusterName)}`,
                    type: 'cluster',
                    label: `Cluster ${clusterName}`,
                    params: { clusterName }
                };

            case 'host':
                const hostname = params?.hostname || '';
                return {
                    path: `/host/${encodeURIComponent(hostname)}`,
                    type: 'host',
                    label: `Host ${hostname}`,
                    params: { hostname }
                };

            case 'vm':
                const vmId = params?.vmId || '';
                return {
                    path: `/virtual-machine/${encodeURIComponent(vmId)}`,
                    type: 'vm',
                    label: `VM ${vmId}`,
                    params: { vmId }
                };

            case 'disconnected':
                return { path: '/disconnected-hosts', type: 'disconnected', label: 'Disconnected Hosts' };

            case 'settings':
                return { path: '/settings', type: 'settings', label: 'Settings' };

            default:
                return { path: '/', type: 'overview', label: 'Overview' };
        }
    }
}

// Export singleton instance
export const navigationStore = new NavigationStore();
