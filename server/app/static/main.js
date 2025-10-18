// Get configuration from backend
const configData = JSON.parse(document.getElementById('config-data').textContent);
const authEnabled = configData.auth_enabled;

// Authentication state
let userInfo = null;
let authCheckInProgress = false;

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

// Update sidebar navigation with dynamic host/VM data
function updateSidebarNavigation(inventory) {
    const hostsList = document.getElementById('hosts-list');
    if (!hostsList || !inventory.hosts) return;
    
    const hosts = inventory.hosts;
    const vms = inventory.vms || [];
    
    if (hosts.length === 0) {
        hostsList.innerHTML = '<li class="empty" style="padding: 8px; font-size: 12px; color: var(--muted-ink);">No hosts</li>';
        return;
    }
    
    // Group VMs by host
    const vmsByHost = {};
    vms.forEach(vm => {
        if (!vmsByHost[vm.host]) {
            vmsByHost[vm.host] = [];
        }
        vmsByHost[vm.host].push(vm);
    });
    
    let navHtml = '';
    hosts.forEach(host => {
        const shortName = host.hostname.split('.')[0];
        const hostVMs = vmsByHost[host.hostname] || [];
        
        navHtml += `
            <li class="nav-group" data-host="${host.hostname}">
                <div class="sub-sub-item group-header" onclick="viewManager.switchView('host', { hostname: '${host.hostname}' })">
                    <span class="sub-sub-icon">🖥</span>
                    <span>${shortName}</span>
                    ${hostVMs.length > 0 ? '<span class="expand-icon">›</span>' : ''}
                </div>
                ${hostVMs.length > 0 ? `
                    <ul class="vm-list">
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
    });
    
    hostsList.innerHTML = navHtml;
    
    // Re-attach event listeners for expand/collapse
    hostsList.querySelectorAll('.group-header .expand-icon').forEach(icon => {
        icon.parentElement.addEventListener('click', (e) => {
            e.stopPropagation();
            const navGroup = e.target.closest('.nav-group');
            navGroup.classList.toggle('expanded');
        });
    });
}

// Call initializeAuth when page loads
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize systems
    overlayManager.init();
    viewManager.init('view-container');
    
    await initializeAuth();
    
    // Load initial inventory
    const inventory = await loadInventory();
    
    // Setup navigation handlers
    setupNavigation();
    
    // Show default view
    await viewManager.switchView('overview');
});

// Setup navigation event handlers
function setupNavigation() {
    // Handle nav group expand/collapse
    document.querySelectorAll('.nav-group .group-header').forEach(header => {
        header.addEventListener('click', (e) => {
            e.stopPropagation();
            const navGroup = header.closest('.nav-group');
            navGroup.classList.toggle('expanded');
        });
    });

    // Handle Aether (overview) click
    document.querySelector('[data-view="overview"]')?.addEventListener('click', () => {
        viewManager.switchView('overview');
    });

    // Handle cluster click
    document.querySelector('[data-level="cluster"] > .group-header')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const navGroup = e.target.closest('.nav-group');
        navGroup.classList.toggle('expanded');
        // Also switch to cluster view
        viewManager.switchView('cluster');
    });

    // Handle hosts group click
    document.querySelector('[data-level="host"] > .group-header')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const navGroup = e.target.closest('.nav-group');
        navGroup.classList.toggle('expanded');
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
        notificationsBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleNotifications();
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
function toggleNotifications() {
    const overlay = document.getElementById('notifications-overlay');
    if (overlay) {
        if (overlay.classList.contains('open')) {
            closeNotifications();
        } else {
            openNotifications();
        }
    }
}

function openNotifications() {
    const overlay = document.getElementById('notifications-overlay');
    if (overlay) {
        overlay.classList.add('open');
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
    console.log('Refreshing inventory...');
    const inventory = await loadInventory();
    
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