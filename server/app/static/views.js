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
                    <div class="stat-value">${inventory.hosts.filter(h => h.connected).length}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Total VMs</div>
                    <div class="stat-value">${inventory.total_vms || 0}</div>
                </article>

                <article class="stat-card">
                    <div class="stat-title">Running VMs</div>
                    <div class="stat-value">${inventory.vms.filter(vm => vm.state === 'Running').length}</div>
                </article>
            </section>

            <div class="view-section">
                <div class="section-header">
                    <h2>Recent Activity</h2>
                </div>
                <div class="activity-list">
                    <p class="empty">No recent activity</p>
                </div>
            </div>

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
        const inventory = await this.fetchInventory();
        
        return `
            <h1 class="page-title">Cluster Details</h1>

            <div class="view-section">
                <div class="section-header">
                    <h2>Hosts in Cluster</h2>
                </div>
                <div class="host-grid">
                    ${this.renderHostCards(inventory.hosts)}
                </div>
            </div>

            <div class="view-section">
                <div class="section-header">
                    <h2>Cluster Resources</h2>
                </div>
                <div class="resource-summary">
                    <p>Total CPU Cores: ${this.calculateTotalCPU(inventory.vms)}</p>
                    <p>Total Memory: ${this.calculateTotalMemory(inventory.vms)} GB</p>
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
                    <button class="action-btn">
                        <span class="action-icon">🔄</span>
                        <span>Restart</span>
                    </button>
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

// Initialize view manager
const viewManager = new ViewManager();
