// Get configuration from backend
const configData = JSON.parse(document.getElementById('config-data').textContent);
const authEnabled = configData.auth_enabled;

// Authentication state
let userInfo = null;
let authCheckInProgress = false;

// WebSocket notification handlers
function setupWebSocketHandlers() {
    // Handle connection status changes
    wsClient.onConnectionStatus((status, data) => {
        console.log('WebSocket status:', status, data);
        updateWebSocketIndicator(status, data);
    });

    // Handle initial state
    wsClient.on('initial_state', (message) => {
        console.log('Received initial state via WebSocket');
        const data = message.data;
        if (data.notifications) {
            updateNotificationPanel({
                notifications: data.notifications,
                unread_count: data.unread_count || 0,
                total_count: data.notifications.length
            });
        }
    });

    // Handle new notifications
    wsClient.on('notification', (message) => {
        console.log('Received notification update via WebSocket:', message);
        handleNotificationUpdate(message);
    });

    // Subscribe to notifications
    wsClient.subscribe(['notifications', 'all']);
}

function updateWebSocketIndicator(status, data) {
    // You can add a visual indicator in the UI here
    const notificationsBtn = document.getElementById('notifications-btn');
    if (!notificationsBtn) return;

    // Remove existing status classes
    notificationsBtn.classList.remove('ws-connected', 'ws-connecting', 'ws-disconnected', 'ws-reconnecting', 'ws-error');
    
    // Add current status class
    if (status === 'connected') {
        notificationsBtn.classList.add('ws-connected');
        notificationsBtn.title = 'Notifications (Live)';
    } else if (status === 'connecting') {
        notificationsBtn.classList.add('ws-connecting');
        notificationsBtn.title = 'Notifications (Connecting...)';
    } else if (status === 'reconnecting') {
        notificationsBtn.classList.add('ws-reconnecting');
        notificationsBtn.title = `Notifications (Reconnecting... attempt ${data.attempt})`;
    } else if (status === 'disconnected' || status === 'error') {
        notificationsBtn.classList.add('ws-disconnected');
        notificationsBtn.title = 'Notifications (Offline)';
    }
}

function handleNotificationUpdate(message) {
    const action = message.action;
    const data = message.data;

    if (action === 'created') {
        // New notification created
        console.log('New notification:', data);
        
        // Reload notifications to get the updated list
        loadNotifications();
        
        // Optionally show a toast notification
        showNotificationToast(data);
    } else if (action === 'updated') {
        // Notification updated (e.g., marked as read)
        console.log('Notification updated:', data);
        
        // Update the UI without full reload
        updateNotificationItem(data);
    }
}

function showNotificationToast(notification) {
    // Simple toast notification - you can enhance this
    console.log('Toast notification:', notification.title);
    // Could implement a toast UI here
}

function updateNotificationItem(data) {
    // Update a specific notification in the list
    const notificationItem = document.querySelector(`[data-notification-id="${data.id}"]`);
    if (notificationItem) {
        if (data.read !== undefined) {
            if (data.read) {
                notificationItem.classList.remove('unread');
            } else {
                notificationItem.classList.add('unread');
            }
        }
    }
}


// Check authentication status from server session (secure)
async function checkAuthenticationStatus() {
    if (authCheckInProgress) {
        return false;
    }
    
    authCheckInProgress = true;
    
    try {
        const response = await fetch('/auth/token', {
            method: 'GET',
            credentials: 'same-origin' // Include session cookies
        });
        
        if (response.ok) {
            const data = await response.json();
            
            if (data.authenticated) {
                userInfo = data.user;
                
                // Always show logout button, but with tooltip if auth disabled
                const logoutBtn = document.getElementById('logout-btn');
                if (logoutBtn) {
                    logoutBtn.style.display = 'block';
                }
                
                console.log('Authentication validated from server session');
                return true;
            } else {
                console.log('Not authenticated:', data.reason);
                // Clear any local state
                userInfo = null;
                localStorage.removeItem('authToken'); // Clean up any old localStorage
                
                // Always show logout button, but with tooltip if auth disabled
                const logoutBtn = document.getElementById('logout-btn');
                if (logoutBtn) {
                    logoutBtn.style.display = 'block';
                }
                
                return false;
            }
        } else {
            console.log('Auth check failed:', response.status);
            return false;
        }
    } catch (error) {
        console.error('Error checking authentication:', error);
        return false;
    } finally {
        authCheckInProgress = false;
    }
}

// Handle authentication callback
async function handleAuthCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const authSuccess = urlParams.get('auth');
    
    if (authSuccess === 'success') {
        // Clean up URL
        const url = new URL(window.location);
        url.searchParams.delete('auth');
        window.history.replaceState({}, '', url);
        
        console.log('Authentication callback received');
        // Check auth status which will update the UI
        return await checkAuthenticationStatus();
    }
    
    return false;
}

// Initialize authentication state
async function initializeAuth() {
    // Clean up any old localStorage tokens since we now use sessions
    localStorage.removeItem('authToken');
    
    // Handle auth callback first
    const callbackHandled = await handleAuthCallback();
    
    if (!callbackHandled) {
        // Check existing session
        const isAuthenticated = await checkAuthenticationStatus();
        
        // If OIDC is enabled and we're not authenticated, redirect to login
        if (authEnabled && !isAuthenticated) {
            console.log('OIDC enabled but not authenticated, redirecting to login');
            setTimeout(() => {
                window.location.href = '/auth/login';
            }, 500); // Small delay to prevent rapid redirects
            return;
        }
    }
    
    // Setup logout button tooltip
    setupLogoutButtonTooltip();
}

// Setup logout button tooltip for when auth is disabled
function setupLogoutButtonTooltip() {
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        if (!authEnabled) {
            logoutBtn.setAttribute('data-tooltip', 'Authentication is disabled');
        }
    }
}

// Secure logout function
async function logout() {
    if (!authEnabled) {
        console.log('OIDC not enabled, no logout needed');
        return;
    }
    
    try {
        // Call the logout endpoint (no auth header needed - uses session)
        await fetch('/auth/logout', { 
            method: 'POST',
            credentials: 'same-origin'
        });
    } catch (error) {
        console.error('Logout error:', error);
    }
    
    // Clear local state
    userInfo = null;
    
    // Keep logout button visible but update tooltip
    setupLogoutButtonTooltip();
    
    // Redirect to login
    window.location.href = '/auth/login';
}

async function loadInventory() {
    try {
        const response = await fetch('/api/v1/inventory', { 
            credentials: 'same-origin'
        });
        
        if (response.status === 401) {
            if (authEnabled) {
                console.log('Token invalid, checking auth state');
                const isAuthenticated = await checkAuthenticationStatus();
                
                if (!isAuthenticated) {
                    console.log('Not authenticated, redirecting to login');
                    setTimeout(() => {
                        window.location.href = '/auth/login';
                    }, 1000);
                    return null;
                }
                
                return loadInventory();
            } else {
                showError('Authentication required. Please configure authentication.');
                return null;
            }
        }
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Update sidebar navigation with hosts and VMs
        updateSidebarNavigation(data);
        
        return data;
        
    } catch (error) {
        console.error('Error loading inventory:', error);
        showError('Failed to load inventory: ' + error.message);
        return null;
    }
}

async function loadNotifications() {
    try {
        const response = await fetch('/api/v1/notifications', { 
            credentials: 'same-origin'
        });
        
        if (response.status === 401) {
            if (authEnabled) {
                console.log('Token invalid for notifications, checking auth state');
                const isAuthenticated = await checkAuthenticationStatus();
                
                if (!isAuthenticated) {
                    console.log('Not authenticated for notifications');
                    return null;
                }
                
                return loadNotifications();
            } else {
                showError('Authentication required for notifications.');
                return null;
            }
        }
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Update notification panel
        updateNotificationPanel(data);
        
        return data;
        
    } catch (error) {
        console.error('Error loading notifications:', error);
        showError('Failed to load notifications: ' + error.message);
        return null;
    }
}

// Update the notification panel with real data
function updateNotificationPanel(notificationsData) {
    const notificationsList = document.querySelector('.notifications-list');
    
    if (!notificationsList || !notificationsData) return;
    
    // Clear existing notifications (remove dummy data)
    notificationsList.innerHTML = '';
    
    if (notificationsData.notifications.length === 0) {
        notificationsList.innerHTML = `
            <div class="notification-item">
                <div class="notification-icon">📭</div>
                <div class="notification-content">
                    <div class="notification-title">No notifications</div>
                    <div class="notification-message">You're all caught up!</div>
                    <div class="notification-time">Now</div>
                </div>
            </div>
        `;
        return;
    }
    
    // Create notification items
    notificationsData.notifications.forEach(notification => {
        const notificationItem = createNotificationItem(notification);
        notificationsList.appendChild(notificationItem);
    });
    
    // Update notification button badge if there are unread notifications
    updateNotificationBadge(notificationsData.unread_count);
}

// Create a notification item element
function createNotificationItem(notification) {
    const item = document.createElement('div');
    item.className = `notification-item${notification.read ? '' : ' unread'}`;
    item.dataset.notificationId = notification.id;
    
    // Get icon based on level and category
    let icon = '📋'; // default
    switch (notification.level) {
        case 'error':
            icon = '⚠️';
            break;
        case 'warning':
            icon = '🔶';
            break;
        case 'success':
            icon = '✅';
            break;
        case 'info':
            icon = '📋';
            break;
    }
    
    // Format time ago
    const timeAgo = formatTimeAgo(new Date(notification.created_at));
    
    item.innerHTML = `
        <div class="notification-icon">${icon}</div>
        <div class="notification-content">
            <div class="notification-title">${notification.title}</div>
            <div class="notification-message">${notification.message}</div>
            <div class="notification-time">${timeAgo}</div>
        </div>
    `;
    
    // Add click handler to mark as read
    item.addEventListener('click', async () => {
        if (!notification.read) {
            await markNotificationAsRead(notification.id);
        }
    });
    
    return item;
}

// Format time ago helper
function formatTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
    return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
}

// Mark notification as read
async function markNotificationAsRead(notificationId) {
    try {
        const response = await fetch(`/api/v1/notifications/${notificationId}/read`, {
            method: 'PUT',
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            // Reload notifications to update UI
            await loadNotifications();
        }
    } catch (error) {
        console.error('Error marking notification as read:', error);
    }
}

// Mark all notifications as read
async function markAllNotificationsAsRead() {
    try {
        const response = await fetch('/api/v1/notifications/read-all', {
            method: 'PUT',
            credentials: 'same-origin'
        });
        
        if (response.ok) {
            // Reload notifications to update UI
            await loadNotifications();
        }
    } catch (error) {
        console.error('Error marking all notifications as read:', error);
    }
}

// Update notification button badge
function updateNotificationBadge(unreadCount) {
    const notificationsBtn = document.getElementById('notifications-btn');
    
    if (!notificationsBtn) return;
    
    // Remove existing badge
    const existingBadge = notificationsBtn.querySelector('.notification-badge');
    if (existingBadge) {
        existingBadge.remove();
    }
    
    // Add badge if there are unread notifications
    if (unreadCount > 0) {
        const badge = document.createElement('span');
        badge.className = 'notification-badge';
        badge.textContent = unreadCount > 99 ? '99+' : unreadCount.toString();
        notificationsBtn.appendChild(badge);
    }
}

// Update sidebar navigation with dynamic cluster/host/VM data
function updateSidebarNavigation(inventory) {
    const clustersContainer = document.getElementById('clusters-container');
    const disconnectedHostsItem = document.querySelector('.disconnected-hosts');
    const disconnectedBadge = document.querySelector('.disconnected-count');
    
    if (!clustersContainer || !inventory) return;
    
    const clusters = inventory.clusters || [];
    const hosts = inventory.hosts || [];
    const vms = inventory.vms || [];
    const disconnectedHosts = inventory.disconnected_hosts || [];
    
    // Get user setting for showing hosts
    const showHosts = localStorage.getItem('setting.showHosts') !== 'false';
    
    // Save current expanded/collapsed state before updating
    const expandedClusters = new Set();
    const expandedHosts = new Set();
    document.querySelectorAll('.nav-group.expanded[data-cluster]').forEach(el => {
        expandedClusters.add(el.dataset.cluster);
    });
    document.querySelectorAll('.nav-group.expanded[data-host]').forEach(el => {
        expandedHosts.add(el.dataset.host);
    });
    
    // Group VMs by host
    const vmsByHost = {};
    vms.forEach(vm => {
        if (!vmsByHost[vm.host]) {
            vmsByHost[vm.host] = [];
        }
        vmsByHost[vm.host].push(vm);
    });
    
    // Group hosts by cluster
    const hostsByCluster = {};
    hosts.forEach(host => {
        const clusterName = host.cluster || 'Default';
        if (!hostsByCluster[clusterName]) {
            hostsByCluster[clusterName] = [];
        }
        hostsByCluster[clusterName].push(host);
    });
    
    // Generate clusters HTML
    let clustersHtml = '';
    
    if (clusters.length === 0) {
        // No clusters available - show empty state
        clustersHtml = `
            <li class="nav-item empty-state" style="padding: 16px 8px; text-align: center; color: var(--muted-ink); font-size: 12px;">
                No hosts connected
            </li>
        `;
    } else {
        clusters.forEach(cluster => {
            const clusterHosts = hostsByCluster[cluster.name] || [];
            const isExpanded = expandedClusters.has(cluster.name);
            
            clustersHtml += `
                <li class="nav-group ${isExpanded ? 'expanded' : ''}" data-cluster="${cluster.name}">
                    <div class="nav-item group-header" onclick="viewManager.switchView('cluster', { name: '${cluster.name}' })">
                        <span class="nav-icon">📦</span>
                        <span class="nav-label">${cluster.name}</span>
                        <span class="expand-icon">›</span>
                    </div>
                    <ul class="sub-list">
                        ${renderClusterContent(cluster, clusterHosts, vmsByHost, showHosts, expandedHosts)}
                    </ul>
                </li>
            `;
        });
    }
    
    clustersContainer.innerHTML = `<ul class="nav-list">${clustersHtml}</ul>`;
    
    // Update disconnected hosts section
    if (disconnectedHosts.length > 0) {
        disconnectedHostsItem.style.display = 'list-item';
        disconnectedBadge.textContent = disconnectedHosts.length;
        disconnectedBadge.style.display = 'inline';
    } else {
        disconnectedHostsItem.style.display = 'none';
        disconnectedBadge.style.display = 'none';
    }
    
    // Re-attach event listeners
    attachNavigationEventListeners();
}

function renderClusterContent(cluster, hosts, vmsByHost, showHosts, expandedHosts = new Set()) {
    if (showHosts) {
        // Show hosts as intermediate level
        return hosts.map(host => {
            const shortName = host.hostname.split('.')[0];
            const hostVMs = vmsByHost[host.hostname] || [];
            const isExpanded = expandedHosts.has(host.hostname);
            
            return `
                <li class="nav-group ${isExpanded ? 'expanded' : ''}" data-host="${host.hostname}">
                    <div class="sub-item group-header" onclick="viewManager.switchView('host', { hostname: '${host.hostname}' })">
                        <span class="sub-icon">🖥️</span>
                        <span class="sub-label">${shortName}</span>
                        ${hostVMs.length > 0 ? '<span class="expand-icon">›</span>' : ''}
                    </div>
                    ${hostVMs.length > 0 ? `
                        <ul class="sub-sub-list">
                            ${hostVMs.map(vm => {
                                const statusEmoji = vm.state === 'Running' ? '🟢' : '⚫';
                                return `
                                    <li class="vm-item" onclick="event.stopPropagation(); viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                                        <span class="vm-status">${statusEmoji}</span>
                                        <span class="vm-name">${vm.name}</span>
                                    </li>
                                `;
                            }).join('')}
                        </ul>
                    ` : ''}
                </li>
            `;
        }).join('');
    } else {
        // Show VMs directly under cluster
        const allVMs = [];
        hosts.forEach(host => {
            const hostVMs = vmsByHost[host.hostname] || [];
            allVMs.push(...hostVMs);
        });
        
        return allVMs.map(vm => {
            const statusEmoji = vm.state === 'Running' ? '🟢' : '⚫';
            const hostShort = vm.host.split('.')[0];
            return `
                <li class="vm-item direct" onclick="viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                    <span class="vm-status">${statusEmoji}</span>
                    <span class="vm-name">${vm.name}</span>
                    <span class="vm-host">(${hostShort})</span>
                </li>
            `;
        }).join('');
    }
}

function attachNavigationEventListeners() {
    // Handle expand icon clicks separately from navigation
    document.querySelectorAll('.expand-icon').forEach(icon => {
        icon.addEventListener('click', (e) => {
            e.stopPropagation();
            const navGroup = icon.closest('.nav-group');
            if (navGroup) {
                navGroup.classList.toggle('expanded');
            }
        });
    });
    
    // Handle disconnected hosts click
    document.querySelector('.disconnected-hosts')?.addEventListener('click', () => {
        viewManager.switchView('disconnected-hosts');
    });
}

// Theme management
function applyTheme(themeMode) {
    const html = document.documentElement;
    
    if (themeMode === 'system') {
        // Use system preference
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        html.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
        html.setAttribute('data-theme', themeMode);
    }
}

function initializeTheme() {
    const themeMode = localStorage.getItem('setting.themeMode') || 'system';
    applyTheme(themeMode);
    
    // Listen for system theme changes if in system mode
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        const currentMode = localStorage.getItem('setting.themeMode') || 'system';
        if (currentMode === 'system') {
            applyTheme('system');
        }
    });
}

// Call initializeAuth when page loads
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize theme first
    initializeTheme();
    
    // Initialize systems
    overlayManager.init();
    viewManager.init('view-container');
    
    // Setup WebSocket handlers
    setupWebSocketHandlers();
    
    await initializeAuth();
    
    // Load initial inventory
    const inventory = await loadInventory();
    
    // Load initial notifications (will also come via WebSocket)
    await loadNotifications();
    
    // Setup navigation handlers
    setupNavigation();
    
    // Show default view
    await viewManager.switchView('overview');
});

// Setup navigation event handlers
function setupNavigation() {
    // Handle Aether (overview) click
    document.querySelector('[data-view="overview"]')?.addEventListener('click', () => {
        viewManager.switchView('overview');
    });

    // Settings button handler
    const settingsBtn = document.getElementById('sidebar-settings');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', () => {
            overlayManager.open('settings');
        });
    }

    // Notifications button handler
    const notificationsBtn = document.getElementById('notifications-btn');
    if (notificationsBtn) {
        notificationsBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await toggleNotifications();
        });
    }
    
    // Mark all as read button handler
    const markAllReadBtn = document.querySelector('.mark-all-read-btn');
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await markAllNotificationsAsRead();
        });
    }
    
    // Close notifications when clicking outside
    document.addEventListener('click', (e) => {
        const notificationsOverlay = document.getElementById('notifications-overlay');
        const notificationsBtn = document.getElementById('notifications-btn');
        
        if (notificationsOverlay && 
            !notificationsOverlay.contains(e.target) && 
            !notificationsBtn.contains(e.target)) {
            closeNotifications();
        }
    });
}

// Notifications overlay management
async function toggleNotifications() {
    const overlay = document.getElementById('notifications-overlay');
    if (overlay) {
        if (overlay.classList.contains('open')) {
            closeNotifications();
        } else {
            await openNotifications();
        }
    }
}

async function openNotifications() {
    const overlay = document.getElementById('notifications-overlay');
    if (overlay) {
        overlay.classList.add('open');
        // Load notifications when panel is opened
        await loadNotifications();
    }
}

function closeNotifications() {
    const overlay = document.getElementById('notifications-overlay');
    if (overlay) {
        overlay.classList.remove('open');
    }
}

function showError(message) {
    console.error('Error:', message);
    // Could show a toast notification here
}

async function refreshInventory() {
    console.log('Refreshing inventory and notifications...');
    
    // Refresh both inventory and notifications
    const inventory = await loadInventory();
    await loadNotifications();
    
    // Refresh current view if it needs updated data
    if (viewManager.currentView && typeof viewManager.currentView.refresh === 'function') {
        await viewManager.currentView.refresh();
    } else if (viewManager.currentView) {
        // Re-render the current view
        const currentViewName = [...viewManager.views.entries()]
            .find(([, ViewClass]) => viewManager.currentView instanceof ViewClass)?.[0];
        if (currentViewName) {
            await viewManager.switchView(currentViewName, viewManager.currentView.data);
        }
    }
}

// Auto-refresh every 30 seconds
setInterval(refreshInventory, 30000);

// Search Overlay Management
class SearchOverlay {
    constructor() {
        this.isOpen = false;
        this.overlayElement = null;
        this.createOverlayDOM();
    }

    createOverlayDOM() {
        const overlay = document.createElement('div');
        overlay.id = 'search-overlay';
        overlay.className = 'search-overlay';
        overlay.innerHTML = `
            <div class="search-backdrop"></div>
            <div class="search-panel">
                <div class="search-panel-header">
                    <input type="text" class="search-panel-input" id="search-panel-input" placeholder="Search for VMs, Hosts, Clusters..." autofocus />
                </div>
                <div class="search-panel-content" id="search-panel-content">
                    ${this.renderEmptyState()}
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        this.overlayElement = overlay;

        // Setup event listeners
        overlay.querySelector('.search-backdrop').addEventListener('click', () => this.close());
        
        // ESC key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });

        // Search input handler
        const searchInput = overlay.querySelector('#search-panel-input');
        searchInput.addEventListener('input', (e) => {
            // TODO: Implement search functionality - filter VMs, Hosts, and Clusters
            // This is a placeholder for future search implementation
        });
    }

    renderEmptyState() {
        return `
            <div class="search-section">
                <div class="search-section-header">Virtual Machines</div>
                <div class="search-no-results">No VMs found</div>
            </div>
            <div class="search-section">
                <div class="search-section-header">Hosts</div>
                <div class="search-no-results">No hosts found</div>
            </div>
            <div class="search-section">
                <div class="search-section-header">Clusters</div>
                <div class="search-no-results">No clusters found</div>
            </div>
        `;
    }

    open() {
        if (this.isOpen) return;
        this.overlayElement.classList.add('open');
        this.isOpen = true;
        document.body.style.overflow = 'hidden';
        
        // Focus search input
        setTimeout(() => {
            const input = this.overlayElement.querySelector('#search-panel-input');
            if (input) input.focus();
        }, 100);
    }

    close() {
        if (!this.isOpen) return;
        this.overlayElement.classList.remove('open');
        this.isOpen = false;
        document.body.style.overflow = '';
        
        // Clear search input
        const input = this.overlayElement.querySelector('#search-panel-input');
        if (input) input.value = '';
        
        // Reset content to empty state
        const content = this.overlayElement.querySelector('#search-panel-content');
        if (content) content.innerHTML = this.renderEmptyState();
    }
}

// Initialize search overlay
const searchOverlay = new SearchOverlay();

// Connect search box to overlay
document.addEventListener('DOMContentLoaded', () => {
    const searchBox = document.getElementById('global-search');
    if (searchBox) {
        searchBox.addEventListener('click', (e) => {
            e.preventDefault();
            searchOverlay.open();
        });
        
        searchBox.addEventListener('focus', (e) => {
            e.preventDefault();
            searchBox.blur();
            searchOverlay.open();
        });
    }
});