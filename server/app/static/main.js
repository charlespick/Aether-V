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
                
                // Show auth controls
                if (authEnabled) {
                    const authControls = document.getElementById('auth-controls');
                    if (authControls) {
                        authControls.style.display = 'block';
                    }
                }
                
                console.log('Authentication validated from server session');
                return true;
            } else {
                console.log('Not authenticated:', data.reason);
                // Clear any local state
                userInfo = null;
                localStorage.removeItem('authToken'); // Clean up any old localStorage
                
                // Hide auth controls
                const authControls = document.getElementById('auth-controls');
                if (authControls) {
                    authControls.style.display = 'none';
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
    
    // Hide logout button
    const authControls = document.getElementById('auth-controls');
    if (authControls) {
        authControls.style.display = 'none';
    }
    
    // Redirect to login
    window.location.href = '/auth/login';
}

// Enhanced loadInventory with better error handling
async function loadInventory() {
    try {
        const response = await fetch('/api/v1/inventory', { 
            credentials: 'same-origin'  // Use session cookies for auth
        });
        
        if (response.status === 401) {
            // Token is invalid - try to refresh auth state
            if (authEnabled) {
                console.log('Token invalid, checking auth state');
                const isAuthenticated = await checkAuthenticationStatus();
                
                if (!isAuthenticated) {
                    console.log('Not authenticated, redirecting to login');
                    setTimeout(() => {
                        window.location.href = '/auth/login';
                    }, 1000);
                    return;
                }
                
                // If we're authenticated now, retry the request
                return loadInventory();
            } else {
                showError('Authentication required. Please configure authentication.');
                return;
            }
        }
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Update stats
        document.getElementById('total-hosts').textContent = data.total_hosts;
        document.getElementById('connected-hosts').textContent = 
            data.hosts.filter(h => h.connected).length;
        document.getElementById('total-vms').textContent = data.total_vms;
        document.getElementById('running-vms').textContent = 
            data.vms.filter(vm => vm.state === 'Running').length;
        
        // Update refresh info
        if (data.last_refresh) {
            const lastRefresh = new Date(data.last_refresh);
            document.getElementById('refresh-info').textContent = 
                `Last updated: ${lastRefresh.toLocaleString()}`;
        }
        
        // Render hosts
        renderHosts(data.hosts);
        
        // Render VMs
        renderVMs(data.vms);
        
    } catch (error) {
        console.error('Error loading inventory:', error);
        showError('Failed to load inventory: ' + error.message);
    }
}

// Call initializeAuth when page loads
document.addEventListener('DOMContentLoaded', initializeAuth);

function renderHosts(hosts) {
    const container = document.getElementById('hosts-content');
    
    if (hosts.length === 0) {
        container.innerHTML = '<div class="empty">No hosts configured</div>';
        return;
    }
    
    let html = '<table><thead><tr><th>Hostname</th><th>Status</th><th>Last Seen</th></tr></thead><tbody>';
    
    for (const host of hosts) {
        const status = host.connected ? 'connected' : 'disconnected';
        const statusText = host.connected ? 'Connected' : 'Disconnected';
        const lastSeen = host.last_seen ? new Date(host.last_seen).toLocaleString() : '-';
        
        html += `
            <tr>
                <td><strong>${host.hostname}</strong></td>
                <td><span class="status ${status}">${statusText}</span></td>
                <td>${lastSeen}</td>
            </tr>
        `;
    }
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

function renderVMs(vms) {
    const container = document.getElementById('vms-content');
    
    if (vms.length === 0) {
        container.innerHTML = '<div class="empty">No VMs found</div>';
        return;
    }
    
    let html = '<table><thead><tr><th>Name</th><th>Host</th><th>State</th><th>CPU Cores</th><th>Memory (GB)</th></tr></thead><tbody>';
    
    for (const vm of vms) {
        const statusClass = vm.state === 'Running' ? 'running' : 'off';
        
        html += `
            <tr>
                <td><strong>${vm.name}</strong></td>
                <td>${vm.host}</td>
                <td><span class="status ${statusClass}">${vm.state}</span></td>
                <td>${vm.cpu_cores}</td>
                <td>${vm.memory_gb.toFixed(2)}</td>
            </tr>
        `;
    }
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

function showError(message) {
    const hostsContent = document.getElementById('hosts-content');
    const vmsContent = document.getElementById('vms-content');
    
    const errorHtml = `<div class="error">${message}</div>`;
    hostsContent.innerHTML = errorHtml;
    vmsContent.innerHTML = errorHtml;
}

async function refreshInventory() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '⏳ Refreshing...';
    
    await loadInventory();
    
    btn.disabled = false;
    btn.textContent = '🔄 Refresh';
}

// Auto-refresh every 30 seconds
setInterval(loadInventory, 30000);