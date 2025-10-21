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

// Connection Status Lifecycle Management
let connectionStatusState = {
    isVisible: false,
    countdownTimer: null,
    reconnectDeadline: null,
    currentStatus: null,
    lastAttempt: null,
    isInErrorState: false,  // Track if we're in any kind of error/disconnection state
    maxAttempts: 10,        // Store max attempts for timer
    messageElement: null    // Store reference to message element for timer
};

// Configuration for different connection states
const CONNECTION_STATES = {
    disconnected: {
        icon: '⚠️',
        title: 'Disconnected',
        message: 'Connection to server lost, attempting to reconnect...',
        buttonText: 'Reconnect Now'
    },
    reconnecting: {
        icon: '⚠️',
        title: 'Disconnected',
        message: 'Trying to reconnect...',
        buttonText: 'Reconnect Now'
    },
    failed: {
        icon: '❌',
        title: 'Connection Failed',
        message: 'Failed to reconnect to server after multiple attempts',
        buttonText: 'Refresh Page'
    }
};

function updateWebSocketIndicator(status, data) {
    const DEFAULT_MAX_RECONNECT_ATTEMPTS = 10; // Fallback if wsClient not available
    
    const indicator = document.getElementById('connection-status-indicator');
    const iconEl = indicator?.querySelector('.connection-status-icon');
    const titleEl = indicator?.querySelector('.connection-status-title');
    const messageEl = indicator?.querySelector('.connection-status-message');
    const retryBtn = document.getElementById('connection-retry-btn');

    if (!indicator || !iconEl || !titleEl || !messageEl || !retryBtn) return;

    // LIFECYCLE PHASE 1: SHOW - First disconnection/error
    if ((status === 'disconnected' || status === 'error' || status === 'reconnecting' || status === 'failed') && !connectionStatusState.isInErrorState) {
        connectionStatusState.isInErrorState = true;
        showConnectionIndicator();
    }

    // LIFECYCLE PHASE 3: HIDE - Back to connected (NOT connecting!)
    if (status === 'connected' && connectionStatusState.isInErrorState) {
        connectionStatusState.isInErrorState = false;
        stopCountdownTimer();
        hideConnectionIndicator();
        return;
    }

    // Ignore 'connecting' status - it's just an attempt, not success
    if (status === 'connecting') {
        return;
    }

    // LIFECYCLE PHASE 2: UPDATE - Any error state updates (don't touch visibility)
    if (connectionStatusState.isInErrorState) {
        updateConnectionContent(status, data, iconEl, titleEl, messageEl, retryBtn, DEFAULT_MAX_RECONNECT_ATTEMPTS);
    }
}

function updateConnectionContent(status, data, iconEl, titleEl, messageEl, retryBtn, maxAttempts) {
    // Get state configuration
    const stateConfig = CONNECTION_STATES[status];
    if (!stateConfig) return;

    // Update content only if status changed
    if (connectionStatusState.currentStatus !== status) {
        connectionStatusState.currentStatus = status;
        
        // Update all content (no DOM visibility changes)
        iconEl.textContent = stateConfig.icon;
        titleEl.textContent = stateConfig.title;
        retryBtn.textContent = stateConfig.buttonText;
    }

    // Handle special case: reconnecting with countdown
    if (status === 'reconnecting' && data && data.delay) {
        // Stop any existing timer first (but don't clear state yet)
        stopCountdownTimer(false);
        
        // Always update state for timer callback (attempt number changes each time)
        connectionStatusState.lastAttempt = data.attempt;
        connectionStatusState.maxAttempts = maxAttempts;
        connectionStatusState.messageElement = messageEl;
        connectionStatusState.reconnectDeadline = Date.now() + data.delay;
        
        // Start countdown timer that updates every second
        connectionStatusState.countdownTimer = setInterval(() => {
            if (connectionStatusState.messageElement && connectionStatusState.lastAttempt) {
                updateCountdownMessage(
                    connectionStatusState.messageElement, 
                    connectionStatusState.lastAttempt, 
                    connectionStatusState.maxAttempts
                );
            }
        }, 1000);
        
        // Update message immediately
        updateCountdownMessage(messageEl, data.attempt, maxAttempts);
    } else {
        // Use the default message for other states
        messageEl.textContent = stateConfig.message;
        stopCountdownTimer();
    }
}

function updateCountdownMessage(messageEl, attempt, maxAttempts) {
    if (!connectionStatusState.reconnectDeadline) {
        messageEl.textContent = `Trying to reconnect... (attempt ${attempt}/${maxAttempts})`;
        return;
    }
    
    const remainingMs = connectionStatusState.reconnectDeadline - Date.now();
    const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
    
    let newMessage;
    if (remainingSeconds > 0) {
        newMessage = `Trying to reconnect... (attempt ${attempt}/${maxAttempts}, retry in ${remainingSeconds}s)`;
    } else {
        newMessage = `Reconnecting... (attempt ${attempt}/${maxAttempts})`;
    }
    
    messageEl.textContent = newMessage;
}

function stopCountdownTimer(clearState = true) {
    if (connectionStatusState.countdownTimer) {
        clearInterval(connectionStatusState.countdownTimer);
        connectionStatusState.countdownTimer = null;
    }
    if (clearState) {
        connectionStatusState.reconnectDeadline = null;
        connectionStatusState.messageElement = null;
    }
}

function showConnectionIndicator() {
    const indicator = document.getElementById('connection-status-indicator');
    if (!indicator || connectionStatusState.isVisible) return;
    
    connectionStatusState.isVisible = true;
    indicator.style.display = 'block';
    
    // Trigger entrance animation
    requestAnimationFrame(() => {
        indicator.classList.add('visible');
    });
}

function hideConnectionIndicator() {
    const indicator = document.getElementById('connection-status-indicator');
    if (!indicator || !connectionStatusState.isVisible) return;
    
    connectionStatusState.isVisible = false;
    connectionStatusState.currentStatus = null;
    connectionStatusState.isInErrorState = false; // Reset error state
    connectionStatusState.lastAttempt = null;
    connectionStatusState.reconnectDeadline = null;
    
    // Trigger exit animation
    indicator.classList.remove('visible');
    
    // Hide after animation completes
    setTimeout(() => {
        if (!connectionStatusState.isVisible) {
            indicator.style.display = 'none';
        }
    }, 300);
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
        const response = await fetch('/api/v1/notifications/mark-all-read', {
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
                        <span class="expand-icon"></span>
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
                        ${hostVMs.length > 0 ? '<span class="expand-icon"></span>' : ''}
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

    // Connection retry button handler
    const retryBtn = document.getElementById('connection-retry-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', () => {
            const btnText = retryBtn.textContent;
            if (btnText === 'Refresh Page') {
                console.log('Manual page refresh requested');
                window.location.reload();
            } else if (btnText === 'Reconnect Now') {
                console.log('Manual reconnect requested');
                // Stop any existing reconnection timer
                if (wsClient.reconnectTimer) {
                    clearTimeout(wsClient.reconnectTimer);
                    wsClient.reconnectTimer = null;
                }
                // Reset attempts to give it more chances
                wsClient.reconnectAttempts = 0;
                // Immediately try to reconnect
                wsClient.connect();
            }
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

// Search Overlay Management - Proper extrude pattern
class SearchOverlay {
    // Time to wait before resetting suppressNextOpen flag after close
    // This ensures focus event handlers complete before the flag is reset
    static SUPPRESS_RESET_DELAY_MS = 100;

    constructor() {
        this.isOpen = false;
        this.suppressNextOpen = false;
        this.overlayElement = null;
        this.expandoElement = null;
        this.originRect = null;
        this.createOverlayDOM();
    }

    createOverlayDOM() {
        const overlay = document.createElement('div');
        overlay.id = 'search-overlay';
        overlay.className = 'search-overlay';
        overlay.setAttribute('aria-hidden', 'true');
        overlay.innerHTML = `
            <div class="search-backdrop"></div>
            <div class="search-expando" role="dialog" aria-modal="true" aria-label="Search results">
                <button class="search-close-btn" aria-label="Close">✕</button>
                <div class="search-expando-header">
                    <div class="search-expando-inner">
                        <input class="search-expando-input" type="text" placeholder="Search Everywhere" aria-label="Search input" />
                    </div>
                </div>
                <div class="search-expando-results">
                    ${this.renderEmptyState()}
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        this.overlayElement = overlay;
        this.expandoElement = overlay.querySelector('.search-expando');

        // Setup event listeners
        const backdrop = overlay.querySelector('.search-backdrop');
        backdrop.addEventListener('click', () => {
            this.close();
        });
        
        const closeBtn = overlay.querySelector('.search-close-btn');
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.close();
        });
        
        // ESC key to close - use a bound method to ensure proper this context
        this.escapeHandler = (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                e.preventDefault();
                this.close();
            }
        };
        document.addEventListener('keydown', this.escapeHandler);

        // Search input handler
        const searchInput = overlay.querySelector('.search-expando-input');
        searchInput.addEventListener('input', (e) => {
            this.performSearch(e.target.value);
        });

        // Prevent expando clicks from closing overlay
        this.expandoElement.addEventListener('click', (e) => {
            e.stopPropagation();
        });

        // Handle resize/scroll to keep overlay aligned
        let resizeTimer;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                if (this.isOpen) {
                    this.calcOrigin();
                    this.updateExpandedPosition();
                }
            }, 80);
        });

        window.addEventListener('scroll', () => {
            if (this.isOpen) {
                this.calcOrigin();
                this.updateExpandedPosition();
            }
        });
    }

    calcOrigin() {
        const pill = document.querySelector('.search-container .search');
        if (pill) {
            this.originRect = pill.getBoundingClientRect();
        } else {
            // Fallback to search container if search input not found
            const container = document.querySelector('.search-container');
            if (container) {
                this.originRect = container.getBoundingClientRect();
            }
        }
    }

    updateExpandedPosition() {
        if (!this.originRect) return;
        
        const rootStyles = getComputedStyle(document.documentElement);
        const rawGap = rootStyles.getPropertyValue('--search-overlay-gap').trim();
        const rootFontSize = parseFloat(rootStyles.fontSize) || 16;
        let paddingPx = parseFloat(rawGap);

        if (Number.isNaN(paddingPx)) {
            paddingPx = 12;
        } else if (rawGap.endsWith('rem')) {
            paddingPx = paddingPx * rootFontSize;
        }

        // Ensure CSS variable stays in sync for nested rules
        this.expandoElement.style.setProperty('--search-overlay-gap', `${paddingPx}px`);

        const viewportPadding = 16;

        // Calculate target dimensions based on original search box
        let targetWidth = this.originRect.width + paddingPx * 2;
        const maxWidth = window.innerWidth - viewportPadding * 2;
        if (targetWidth > maxWidth) {
            targetWidth = maxWidth;
        }

        // Keep overlay growing from original pill
        let targetLeft = this.originRect.left - paddingPx;
        const maxLeft = window.innerWidth - targetWidth - viewportPadding;
        const minLeft = viewportPadding;
        if (targetLeft < minLeft) {
            targetLeft = minLeft;
        }
        if (targetLeft > maxLeft) {
            targetLeft = Math.max(minLeft, maxLeft);
        }

        let targetTop = this.originRect.top - paddingPx;
        if (targetTop < viewportPadding) {
            targetTop = viewportPadding;
        }

        const headerElement = this.expandoElement.querySelector('.search-expando-header');
        const headerHeight = headerElement ? headerElement.offsetHeight : this.originRect.height;
        const resultsElement = this.expandoElement.querySelector('.search-expando-results');

        let resultsHeight = 0;
        let resultsMargin = 0;
        if (resultsElement) {
            resultsHeight = resultsElement.scrollHeight;
            const resultsStyles = getComputedStyle(resultsElement);
            const marginTop = parseFloat(resultsStyles.marginTop) || 0;
            const marginBottom = parseFloat(resultsStyles.marginBottom) || 0;
            resultsMargin = marginTop + marginBottom;
        }

        const minHeight = headerHeight + paddingPx * 2;
        const availableHeight = Math.max(window.innerHeight - targetTop - viewportPadding, minHeight);
        const naturalHeight = headerHeight + resultsHeight + paddingPx * 2 + resultsMargin;
        let targetHeight = Math.min(naturalHeight, availableHeight);

        if (availableHeight >= minHeight) {
            targetHeight = Math.max(targetHeight, minHeight);
        } else {
            targetHeight = availableHeight;
        }

        const interiorHeight = Math.max(targetHeight - (paddingPx * 2) - headerHeight - resultsMargin, 0);

        if (resultsElement) {
            resultsElement.style.maxHeight = `${interiorHeight}px`;
        }

        // Calculate concentric border radius
        const originalInput = document.querySelector('.search-container .search');
        let borderRadius = 20; // fallback
        if (originalInput) {
            const computed = getComputedStyle(originalInput);
            borderRadius = parseFloat(computed.borderRadius) || 20;
        }
        const concentricRadius = borderRadius + paddingPx;

        this.expandoElement.style.left = targetLeft + 'px';
        this.expandoElement.style.width = targetWidth + 'px';
        this.expandoElement.style.top = targetTop + 'px';
        this.expandoElement.style.height = targetHeight + 'px';
        this.expandoElement.style.borderRadius = concentricRadius + 'px';
    }

    renderEmptyState() {
        return `
            <div class="search-section">
                <div class="search-section-header">Virtual Machines</div>
                <div class="search-no-results">Start typing to search...</div>
            </div>
            <div class="search-section">
                <div class="search-section-header">Hosts</div>
                <div class="search-no-results">Start typing to search...</div>
            </div>
            <div class="search-section">
                <div class="search-section-header">Clusters</div>
                <div class="search-no-results">Start typing to search...</div>
            </div>
        `;
    }

    async performSearch(query) {
        if (!query.trim()) {
            const content = this.overlayElement.querySelector('.search-expando-results');
            if (content) {
                content.innerHTML = this.renderEmptyState();
                requestAnimationFrame(() => this.updateExpandedPosition());
            }
            return;
        }

        // Get inventory data for searching
        try {
            const response = await fetch('/api/v1/inventory', { 
                credentials: 'same-origin'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const inventory = await response.json();
            this.renderSearchResults(query, inventory);
        } catch (error) {
            console.error('Error searching inventory:', error);
        }
    }

    renderSearchResults(query, inventory) {
        const content = this.overlayElement.querySelector('.search-expando-results');
        if (!content) return;

        const queryLower = query.toLowerCase();
        
        // Filter VMs
        const vms = (inventory.vms || []).filter(vm => 
            vm.name.toLowerCase().includes(queryLower) || 
            vm.host.toLowerCase().includes(queryLower)
        );

        // Filter Hosts
        const hosts = (inventory.hosts || []).filter(host => 
            host.hostname.toLowerCase().includes(queryLower) ||
            (host.cluster && host.cluster.toLowerCase().includes(queryLower))
        );

        // Filter Clusters
        const clusters = (inventory.clusters || []).filter(cluster => 
            cluster.name.toLowerCase().includes(queryLower)
        );

        let html = '';

        // VMs section
        html += `<div class="search-section">
            <div class="search-section-header">Virtual Machines</div>`;
        if (vms.length > 0) {
            html += '<ul class="search-results-list">';
            vms.forEach(vm => {
                const statusEmoji = vm.state === 'Running' ? '🟢' : '⚫';
                const hostShort = vm.host.split('.')[0];
                html += `
                    <li class="search-result-item" onclick="searchOverlay.close(); viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                        <span class="search-result-icon">${statusEmoji}</span>
                        <div class="search-result-details">
                            <div class="search-result-title">${vm.name}</div>
                            <div class="search-result-subtitle">on ${hostShort} • ${vm.state}</div>
                        </div>
                    </li>
                `;
            });
            html += '</ul>';
        } else {
            html += '<div class="search-no-results">No VMs found</div>';
        }
        html += '</div>';

        // Hosts section
        html += `<div class="search-section">
            <div class="search-section-header">Hosts</div>`;
        if (hosts.length > 0) {
            html += '<ul class="search-results-list">';
            hosts.forEach(host => {
                const shortName = host.hostname.split('.')[0];
                const statusEmoji = host.status === 'connected' ? '🟢' : '🔴';
                html += `
                    <li class="search-result-item" onclick="searchOverlay.close(); viewManager.switchView('host', { hostname: '${host.hostname}' })">
                        <span class="search-result-icon">🖥️</span>
                        <div class="search-result-details">
                            <div class="search-result-title">${shortName}</div>
                            <div class="search-result-subtitle">${host.cluster || 'Default'} • ${host.status}</div>
                        </div>
                    </li>
                `;
            });
            html += '</ul>';
        } else {
            html += '<div class="search-no-results">No hosts found</div>';
        }
        html += '</div>';

        // Clusters section
        html += `<div class="search-section">
            <div class="search-section-header">Clusters</div>`;
        if (clusters.length > 0) {
            html += '<ul class="search-results-list">';
            clusters.forEach(cluster => {
                html += `
                    <li class="search-result-item" onclick="searchOverlay.close(); viewManager.switchView('cluster', { name: '${cluster.name}' })">
                        <span class="search-result-icon">📦</span>
                        <div class="search-result-details">
                            <div class="search-result-title">${cluster.name}</div>
                            <div class="search-result-subtitle">Cluster</div>
                        </div>
                    </li>
                `;
            });
            html += '</ul>';
        } else {
            html += '<div class="search-no-results">No clusters found</div>';
        }
        html += '</div>';

        content.innerHTML = html;
        requestAnimationFrame(() => this.updateExpandedPosition());
    }

    open() {
        if (this.isOpen) return;
        if (this.suppressNextOpen) {
            this.suppressNextOpen = false;
            return;
        }
        this.isOpen = true;
        
        const originalInput = document.querySelector('#global-search');
        const expandoInput = this.overlayElement.querySelector('.search-expando-input');
        
        // Set aria-expanded on original search container
        const searchContainer = document.querySelector('.search-container');
        if (searchContainer) {
            searchContainer.setAttribute('aria-expanded', 'true');
        }

        // Calculate position of original pill
        this.calcOrigin();

        // Start the expando exactly over the pill
        const searchInput = document.querySelector('.search-container .search');
        let initialBorderRadius = 20; // fallback
        if (searchInput) {
            const computed = getComputedStyle(searchInput);
            initialBorderRadius = parseFloat(computed.borderRadius) || 20;
        }
        
        this.expandoElement.style.left = this.originRect.left + 'px';
        this.expandoElement.style.top = this.originRect.top + 'px';
        this.expandoElement.style.width = this.originRect.width + 'px';
        this.expandoElement.style.height = this.originRect.height + 'px';
        this.expandoElement.style.borderRadius = initialBorderRadius + 'px';

        // Copy placeholder and value to make it seamless
        if (originalInput && expandoInput) {
            expandoInput.placeholder = originalInput.placeholder;
            expandoInput.value = originalInput.value || '';
            if (originalInput.value) {
                this.performSearch(originalInput.value);
            }
        }

        // Show backdrop
        this.overlayElement.classList.add('active');
        this.overlayElement.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';

        // Force layout pass then animate to expanded size
        requestAnimationFrame(() => {
            this.expandoElement.classList.add('open');
            this.updateExpandedPosition();

            // Move focus into overlay input after transition starts
            setTimeout(() => {
                if (expandoInput) {
                    expandoInput.focus();
                    expandoInput.setSelectionRange(expandoInput.value.length, expandoInput.value.length);
                }
            }, 220);
        });
    }

    close() {
        if (!this.isOpen) return;
        this.isOpen = false;
        this.suppressNextOpen = true;

        const originalInput = document.querySelector('#global-search');
        const expandoInput = this.overlayElement.querySelector('.search-expando-input');
        
        // Set aria-expanded on original search container
        const searchContainer = document.querySelector('.search-container');
        if (searchContainer) {
            searchContainer.setAttribute('aria-expanded', 'false');
        }

        // Revert expando back to pill size and position
        this.expandoElement.classList.remove('open');
        this.calcOrigin();
        
        // Reset to original search box dimensions and border radius
        const searchInput = document.querySelector('.search-container .search');
        let borderRadius = 20; // fallback
        if (searchInput) {
            const computed = getComputedStyle(searchInput);
            borderRadius = parseFloat(computed.borderRadius) || 20;
        }
        
        this.expandoElement.style.left = this.originRect.left + 'px';
        this.expandoElement.style.top = this.originRect.top + 'px';
        this.expandoElement.style.width = this.originRect.width + 'px';
        this.expandoElement.style.height = this.originRect.height + 'px';
        this.expandoElement.style.borderRadius = borderRadius + 'px';

        // After closing transition, hide backdrop
        const onTransitionEnd = (e) => {
            if (e.target !== this.expandoElement) return;
            this.overlayElement.classList.remove('active');
            this.overlayElement.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
            this.expandoElement.removeEventListener('transitionend', onTransitionEnd);
        };
        this.expandoElement.addEventListener('transitionend', onTransitionEnd);

        // Clear search input and reset content
        if (expandoInput) expandoInput.value = '';
        if (originalInput) originalInput.value = '';
        const content = this.overlayElement.querySelector('.search-expando-results');
        if (content) content.innerHTML = this.renderEmptyState();

        // Return focus to original input and reset suppressNextOpen after sufficient delay
        if (originalInput) {
            originalInput.focus();
            // Allow time for focus event handlers to complete before resetting flag
            setTimeout(() => {
                this.suppressNextOpen = false;
            }, SearchOverlay.SUPPRESS_RESET_DELAY_MS);
        } else {
            // Reset after same delay to maintain consistent behavior
            setTimeout(() => {
                this.suppressNextOpen = false;
            }, SearchOverlay.SUPPRESS_RESET_DELAY_MS);
        }
    }

    destroy() {
        // Clean up event listeners to prevent memory leaks
        if (this.escapeHandler) {
            document.removeEventListener('keydown', this.escapeHandler);
        }
        if (this.overlayElement) {
            this.overlayElement.remove();
        }
    }
}

// Initialize search overlay
const searchOverlay = new SearchOverlay();

// Connect search box to overlay
document.addEventListener('DOMContentLoaded', () => {
    const searchContainer = document.querySelector('.search-container');
    const searchBox = document.getElementById('global-search');
    
    if (searchContainer && searchBox) {
        // Set initial aria-expanded
        searchContainer.setAttribute('aria-expanded', 'false');
        
        // Handle clicks on search container
        searchContainer.addEventListener('click', (e) => {
            if (searchOverlay.suppressNextOpen) {
                searchOverlay.suppressNextOpen = false;
                return;
            }
            e.preventDefault();
            searchOverlay.open();
        });
        
        // Handle Enter/Space on search container
        searchContainer.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                if (searchOverlay.suppressNextOpen) {
                    searchOverlay.suppressNextOpen = false;
                    return;
                }
                e.preventDefault();
                searchOverlay.open();
            }
        });
        
        // Handle focus on search input - redirect to overlay
        searchBox.addEventListener('focus', (e) => {
            if (searchOverlay.isOpen) {
                return;
            }

            if (searchOverlay.suppressNextOpen) {
                searchOverlay.suppressNextOpen = false;
                return;
            }

            e.preventDefault();
            searchBox.blur();
            searchOverlay.open();
        });

        // Handle typing in original search box - redirect to overlay
        searchBox.addEventListener('keydown', (e) => {
            if (searchOverlay.suppressNextOpen) {
                searchOverlay.suppressNextOpen = false;
                return;
            }

            e.preventDefault();
            searchOverlay.open();
            // After opening, transfer the typed character to the overlay input
            setTimeout(() => {
                const overlayInput = document.querySelector('.search-expando-input');
                if (overlayInput && e.key.length === 1) {
                    overlayInput.value = e.key;
                    overlayInput.focus();
                    searchOverlay.performSearch(e.key);
                }
            }, 250);
        });
    }
});