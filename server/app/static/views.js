// View System - Dynamic content management
class ViewManager {
    constructor() {
        this.currentView = null;
        this.viewContainer = null;
        this.views = new Map();
        this.state = {};
    }

    init(containerId) {
        this.viewContainer = document.getElementById(containerId);
        if (!this.viewContainer) {
            console.error('View container not found:', containerId);
            return;
        }
        this.registerDefaultViews();
    }

    registerView(name, viewClass) {
        this.views.set(name, viewClass);
    }

    async switchView(viewName, data = {}) {
        const ViewClass = this.views.get(viewName);
        if (!ViewClass) {
            console.error('View not found:', viewName);
            return;
        }

        // Clean up current view
        if (this.currentView && typeof this.currentView.cleanup === 'function') {
            this.currentView.cleanup();
        }

        // Create and render new view
        this.currentView = new ViewClass(data);
        const html = await this.currentView.render();
        this.viewContainer.innerHTML = html;

        // Initialize the new view
        if (typeof this.currentView.init === 'function') {
            this.currentView.init();
        }

        // Update navigation active state
        this.updateNavigation(viewName);
    }

    updateNavigation(viewName) {
        // Remove active from all nav items
        document.querySelectorAll('.nav-item, .sub-item, .sub-sub-item, .vm-item').forEach(item => {
            item.classList.remove('active');
        });

        // Add active to current view's nav item
        const navItem = document.querySelector(`[data-view="${viewName}"]`);
        if (navItem) {
            navItem.classList.add('active');
        }
    }

    registerDefaultViews() {
        this.registerView('overview', OverviewView);
        this.registerView('cluster', ClusterView);
        this.registerView('host', HostView);
        this.registerView('vm', VMView);
        this.registerView('disconnected-hosts', DisconnectedHostsView);
    }
}

// Base View Class
class BaseView {
    constructor(data = {}) {
        this.data = data;
    }

    async render() {
        return '<div>Base View - Override this method</div>';
    }

    init() {
        // Override to add event listeners, etc.
    }

    cleanup() {
        // Override to clean up event listeners, timers, etc.
    }
}

// Overview View (Aether root)
class OverviewView extends BaseView {
    async render() {
        // Fetch latest inventory data
        const inventory = await this.fetchInventory();
        
        return `
            <h1 class="page-title">Aether Overview</h1>

            <section class="stats-row" aria-label="Overview stats">
                <article class="stat-card">
                    <div class="stat-title">Total Hosts</div>
                    <div class="stat-value">${inventory.total_hosts || 0}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Connected Hosts</div>
                    <div class="stat-value">${(inventory.hosts || []).filter(h => h.connected).length}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Total VMs</div>
                    <div class="stat-value">${inventory.total_vms || 0}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Running VMs</div>
                    <div class="stat-value">${(inventory.vms || []).filter(vm => vm.state === 'Running').length}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Clusters</div>
                    <div class="stat-value">${(inventory.clusters || []).length}</div>
                </article>
            </section>

            ${(inventory.hosts || []).length === 0 ? `
                <div class="view-section">
                    <div class="section-header">
                        <h2>${(inventory.disconnected_hosts || []).length > 0 ? 'Connection Issues' : 'Getting Started'}</h2>
                    </div>
                    <div class="empty-state">
                        ${(inventory.disconnected_hosts || []).length > 0 ? `
                            <div class="empty-icon">⚠️</div>
                            <div class="empty-title">No hosts connected</div>
                            <div class="empty-description">
                                ${(inventory.disconnected_hosts || []).length} host(s) are configured but currently unreachable.
                                <br><br>
                                <strong>Troubleshooting steps:</strong>
                                <br>• Check network connectivity to hosts
                                <br>• Verify WinRM is enabled and configured
                                <br>• Confirm credentials are correct
                                <br>• Check firewall settings on hosts
                                <br><br>
                                <button class="action-btn" onclick="viewManager.switchView('disconnected-hosts')" style="margin-top: 12px;">
                                    <span class="action-icon">⚠️</span>
                                    <span>View Disconnected Hosts</span>
                                </button>
                            </div>
                        ` : `
                            <div class="empty-icon">🖥️</div>
                            <div class="empty-title">No hosts configured</div>
                            <div class="empty-description">
                                Configure Hyper-V hosts in your environment settings to begin managing virtual machines.
                                <br><br>
                                Set the <code>HYPERV_HOSTS</code> environment variable with comma-separated host names.
                            </div>
                        `}
                    </div>
                </div>
            ` : `
                <div class="view-section">
                    <div class="section-header">
                        <h2>Recent Activity</h2>
                    </div>
                    <div class="activity-list">
                        <p class="empty">No recent activity</p>
                    </div>
                </div>
            `}

            <div class="view-section">
                <div class="section-header">
                    <h2>Quick Actions</h2>
                </div>
                <div class="quick-actions">
                    <button class="action-btn" onclick="overlayManager.open('settings')">
                        <span class="action-icon">⚙️</span>
                        <span>Settings</span>
                    </button>
                    <button class="action-btn" onclick="refreshInventory()">
                        <span class="action-icon">🔄</span>
                        <span>Refresh All</span>
                    </button>
                </div>
            </div>
        `;
    }

    async fetchInventory() {
        try {
            const response = await fetch('/api/v1/inventory', {
                credentials: 'same-origin'
            });
            if (response.ok) {
                return await response.json();
            }
        } catch (error) {
            console.error('Error fetching inventory:', error);
        }
        return { hosts: [], vms: [], total_hosts: 0, total_vms: 0 };
    }
}

// Cluster View
class ClusterView extends BaseView {
    async render() {
        const clusterName = this.data.name || 'Unknown Cluster';
        const inventory = await this.fetchInventory();
        
        // Filter hosts and VMs for this specific cluster
        const clusterHosts = inventory.hosts.filter(h => h.cluster === clusterName);
        const clusterVMs = inventory.vms.filter(vm => {
            const vmHost = inventory.hosts.find(h => h.hostname === vm.host);
            return vmHost && vmHost.cluster === clusterName;
        });
        
        return `
            <h1 class="page-title">${clusterName}</h1>

            <div class="view-section">
                <div class="section-header">
                    <h2>Hosts in Cluster</h2>
                </div>
                <div class="host-grid">
                    ${this.renderHostCards(clusterHosts)}
                </div>
            </div>

            <div class="view-section">
                <div class="section-header">
                    <h2>Virtual Machines</h2>
                </div>
                <div class="vm-grid">
                    ${this.renderVMCards(clusterVMs)}
                </div>
            </div>

            <div class="view-section">
                <div class="section-header">
                    <h2>Cluster Resources</h2>
                </div>
                <div class="resource-summary">
                    <p>Total CPU Cores: ${this.calculateTotalCPU(clusterVMs)}</p>
                    <p>Total Memory: ${this.calculateTotalMemory(clusterVMs)} GB</p>
                </div>
            </div>
        `;
    }

    renderHostCards(hosts) {
        if (hosts.length === 0) {
            return '<p class="empty">No hosts configured</p>';
        }

        return hosts.map(host => `
            <div class="host-card" onclick="viewManager.switchView('host', { hostname: '${host.hostname}' })">
                <div class="host-card-header">
                    <span class="host-icon">🖥️</span>
                    <span class="host-name">${host.hostname}</span>
                </div>
                <div class="host-card-status">
                    <span class="status ${host.connected ? 'connected' : 'disconnected'}">
                        ${host.connected ? 'Connected' : 'Disconnected'}
                    </span>
                </div>
            </div>
        `).join('');
    }

    renderVMCards(vms) {
        if (vms.length === 0) {
            return '<p class="empty">No virtual machines</p>';
        }

        return vms.map(vm => `
            <div class="vm-card" onclick="viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                <div class="vm-card-header">
                    <span class="vm-status-icon">${vm.state === 'Running' ? '🟢' : '⚫'}</span>
                    <span class="vm-card-name">${vm.name}</span>
                </div>
                <div class="vm-card-details">
                    <div class="vm-card-spec">${vm.cpu_cores} vCPU</div>
                    <div class="vm-card-spec">${vm.memory_gb.toFixed(2)} GB RAM</div>
                    <div class="vm-card-host">Host: ${vm.host.split('.')[0]}</div>
                </div>
                <div class="vm-card-status">
                    <span class="status ${vm.state === 'Running' ? 'running' : 'off'}">${vm.state.toUpperCase()}</span>
                </div>
            </div>
        `).join('');
    }

    calculateTotalCPU(vms) {
        return vms.reduce((sum, vm) => sum + (vm.cpu_cores || 0), 0);
    }

    calculateTotalMemory(vms) {
        return vms.reduce((sum, vm) => sum + (vm.memory_gb || 0), 0).toFixed(2);
    }

    async fetchInventory() {
        try {
            const response = await fetch('/api/v1/inventory', { credentials: 'same-origin' });
            if (response.ok) return await response.json();
        } catch (error) {
            console.error('Error:', error);
        }
        return { hosts: [], vms: [] };
    }
}

// Host View
class HostView extends BaseView {
    async render() {
        const hostname = this.data.hostname || 'Unknown Host';
        const inventory = await this.fetchInventory();
        const host = inventory.hosts.find(h => h.hostname === hostname);
        const hostVMs = inventory.vms.filter(vm => vm.host === hostname);

        return `
            <h1 class="page-title">${hostname}</h1>

            <div class="view-section">
                <div class="section-header">
                    <h2>Host Information</h2>
                </div>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">Status:</span>
                        <span class="status ${host?.connected ? 'connected' : 'disconnected'}">
                            ${host?.connected ? 'Connected' : 'Disconnected'}
                        </span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Last Seen:</span>
                        <span>${host?.last_seen ? new Date(host.last_seen).toLocaleString() : 'Never'}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">VM Count:</span>
                        <span>${hostVMs.length}</span>
                    </div>
                </div>
            </div>

            <div class="view-section">
                <div class="section-header">
                    <h2>Virtual Machines</h2>
                </div>
                <div class="vm-list-view">
                    ${this.renderVMList(hostVMs)}
                </div>
            </div>
        `;
    }

    renderVMList(vms) {
        if (vms.length === 0) {
            return '<p class="empty">No VMs on this host</p>';
        }

        return vms.map(vm => `
            <div class="vm-card" onclick="viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                <div class="vm-card-header">
                    <span class="vm-status-dot ${vm.state === 'Running' ? 'running' : 'off'}"></span>
                    <span class="vm-name">${vm.name}</span>
                </div>
                <div class="vm-card-details">
                    <span>${vm.cpu_cores} vCPU</span>
                    <span>${vm.memory_gb.toFixed(2)} GB RAM</span>
                    <span class="status ${vm.state === 'Running' ? 'running' : 'off'}">${vm.state}</span>
                </div>
            </div>
        `).join('');
    }

    async fetchInventory() {
        try {
            const response = await fetch('/api/v1/inventory', { credentials: 'same-origin' });
            if (response.ok) return await response.json();
        } catch (error) {
            console.error('Error:', error);
        }
        return { hosts: [], vms: [] };
    }
}

// VM View
class VMView extends BaseView {
    async render() {
        const vmName = this.data.name || 'Unknown VM';
        const inventory = await this.fetchInventory();
        const vm = inventory.vms.find(v => v.name === vmName);

        if (!vm) {
            return `
                <h1 class="page-title">VM Not Found</h1>
                <p class="empty">Virtual machine "${vmName}" not found</p>
            `;
        }

        return `
            <h1 class="page-title">${vm.name}</h1>

            <div class="view-section">
                <div class="section-header">
                    <h2>VM Details</h2>
                </div>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">State:</span>
                        <span class="status ${vm.state === 'Running' ? 'running' : 'off'}">${vm.state}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Host:</span>
                        <span>${vm.host}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">CPU Cores:</span>
                        <span>${vm.cpu_cores}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Memory:</span>
                        <span>${vm.memory_gb.toFixed(2)} GB</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Version:</span>
                        <span>${vm.version || 'Unknown'}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Generation:</span>
                        <span>${vm.generation || 'Unknown'}</span>
                    </div>
                </div>
            </div>

            <div class="view-section">
                <div class="section-header">
                    <h2>Actions</h2>
                </div>
                <div class="vm-actions">
                    <button class="action-btn ${vm.state === 'Running' ? '' : 'disabled'}" ${vm.state !== 'Running' ? 'disabled' : ''}>
                        <span class="action-icon">⏸️</span>
                        <span>Stop</span>
                    </button>
                    <button class="action-btn ${vm.state !== 'Running' ? '' : 'disabled'}" ${vm.state === 'Running' ? 'disabled' : ''}>
                        <span class="action-icon">▶️</span>
                        <span>Start</span>
                    </button>
                    ${vm.state === 'Running' ? `
                    <button class="action-btn">
                        <span class="action-icon">🔄</span>
                        <span>Restart</span>
                    </button>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async fetchInventory() {
        try {
            const response = await fetch('/api/v1/inventory', { credentials: 'same-origin' });
            if (response.ok) return await response.json();
        } catch (error) {
            console.error('Error:', error);
        }
        return { hosts: [], vms: [] };
    }
}

// Disconnected Hosts View
class DisconnectedHostsView extends BaseView {
    async render() {
        const inventory = await this.fetchInventory();
        const disconnectedHosts = inventory.disconnected_hosts || [];

        return `
            <h1 class="page-title">Disconnected Hosts</h1>

            <div class="view-section">
                <div class="section-header">
                    <h2>Hosts Not Currently Connected</h2>
                    <p class="section-description">
                        These hosts are configured but currently unreachable. Check network connectivity, 
                        WinRM configuration, or host availability.
                    </p>
                </div>
                
                ${disconnectedHosts.length === 0 ? `
                    <div class="empty-state">
                        <div class="empty-icon">✅</div>
                        <div class="empty-title">All hosts are connected</div>
                        <div class="empty-description">Great! All configured hosts are currently reachable.</div>
                    </div>
                ` : `
                    <div class="host-grid">
                        ${this.renderDisconnectedHosts(disconnectedHosts)}
                    </div>
                `}
            </div>
        `;
    }

    renderDisconnectedHosts(hosts) {
        return hosts.map(host => `
            <div class="host-card disconnected">
                <div class="host-card-header">
                    <span class="host-icon">⚠️</span>
                    <span class="host-name">${host.hostname}</span>
                </div>
                <div class="host-card-status">
                    <span class="status disconnected">Disconnected</span>
                    ${host.last_seen ? `
                        <div class="last-seen">
                            Last seen: ${new Date(host.last_seen).toLocaleString()}
                        </div>
                    ` : ''}
                </div>
                ${host.error ? `
                    <div class="host-error">
                        <strong>Error:</strong> ${host.error}
                    </div>
                ` : ''}
                <div class="host-actions">
                    <button class="action-btn retry" onclick="retryHostConnection('${host.hostname}')">
                        <span class="action-icon">🔄</span>
                        <span>Retry Connection</span>
                    </button>
                </div>
            </div>
        `).join('');
    }

    async fetchInventory() {
        try {
            const response = await fetch('/api/v1/inventory', { credentials: 'same-origin' });
            if (response.ok) return await response.json();
        } catch (error) {
            console.error('Error:', error);
        }
        return { disconnected_hosts: [] };
    }
}

// Helper function for retry connection button
async function retryHostConnection(hostname) {
    console.log('Retrying connection to:', hostname);
    // In a real implementation, this would trigger a refresh for the specific host
    await refreshInventory();
    // Show a toast or notification about the retry attempt
}

// Initialize view manager
const viewManager = new ViewManager();
