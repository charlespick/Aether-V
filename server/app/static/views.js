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

        if (typeof window.applyProvisioningAvailability === 'function') {
            window.applyProvisioningAvailability(window.agentDeploymentState);
        }
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
                <div class="view-section surface-card">
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
                <div class="view-section surface-card">
                    <div class="section-header">
                        <h2>Recent Activity</h2>
                    </div>
                    <div class="activity-list">
                        <p class="empty">No recent activity</p>
                    </div>
                </div>
            `}

            <div class="view-section surface-card">
                <div class="section-header">
                    <h2>Quick Actions</h2>
                </div>
                <div class="quick-actions">
                    <button class="action-btn" data-action="open-provision" onclick="overlayManager.open('provision-job')">
                        <span class="action-icon">🆕</span>
                        <span>Create VM</span>
                    </button>
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

            <div class="view-section surface-card">
                <div class="section-header">
                    <h2>Hosts in Cluster</h2>
                </div>
                <div class="host-grid">
                    ${this.renderHostCards(clusterHosts)}
                </div>
            </div>

            <div class="view-section surface-card">
                <div class="section-header">
                    <h2>Virtual Machines</h2>
                </div>
                <div class="vm-grid">
                    ${this.renderVMCards(clusterVMs)}
                </div>
            </div>

            <div class="view-section surface-card">
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

        return vms.map(vm => {
            const meta = getVmStateMeta(vm.state);
            return `
                <div class="vm-card" onclick="viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                    <div class="vm-card-header">
                        <span class="vm-status-icon">${meta.emoji}</span>
                        <span class="vm-card-name">${vm.name}</span>
                    </div>
                    <div class="vm-card-details">
                        <div class="vm-card-spec">${vm.cpu_cores ?? 0} vCPU</div>
                        <div class="vm-card-spec">${Number(vm.memory_gb ?? 0).toFixed(2)} GB RAM</div>
                        <div class="vm-card-host">Host: ${vm.host.split('.')[0]}</div>
                    </div>
                    <div class="vm-card-status">
                        <span class="status ${meta.badgeClass}">${meta.label.toUpperCase()}</span>
                    </div>
                </div>
            `;
        }).join('');
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

            <div class="view-section surface-card">
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

            <div class="view-section surface-card">
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

        return vms.map(vm => {
            const meta = getVmStateMeta(vm.state);
            return `
                <div class="vm-card" onclick="viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })">
                    <div class="vm-card-header">
                        <span class="vm-status-dot ${meta.dotClass}"></span>
                        <span class="vm-name">${vm.name}</span>
                    </div>
                    <div class="vm-card-details">
                        <span>${vm.cpu_cores ?? 0} vCPU</span>
                        <span>${Number(vm.memory_gb ?? 0).toFixed(2)} GB RAM</span>
                        <span class="status ${meta.badgeClass}">${meta.label}</span>
                    </div>
                </div>
            `;
        }).join('');
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
        const requestedHost = this.data.host || null;
        const inventory = await this.fetchInventory();
        const vm = this.findVm(inventory, vmName, requestedHost);

        if (!vm) {
            return `
                <h1 class="page-title">VM Not Found</h1>
                <p class="empty">Virtual machine "${vmName}" not found</p>
            `;
        }

        this.vmData = vm;
        this.vmHost = vm.host;
        this.lastInventory = inventory;

        const meta = getVmStateMeta(vm.state);
        const osName = this.formatOsFamily(vm);
        const hostInfo = this.findHost(inventory, vm.host);
        const overviewItems = [
            { label: 'Hyper-V Host', value: this.formatHostname(vm.host) },
            { label: 'IP Address(es)', value: this.extractIpAddresses(vm) },
            { label: 'Operating System', value: osName },
            { label: 'Clustered', value: this.formatClusterState(vm, hostInfo) },
            { label: 'Created', value: this.formatDate(vm.created_at) }
        ];

        const hardwareItems = [
            { label: 'CPU Cores', value: this.formatValue(vm.cpu_cores, '—') },
            { label: 'Memory', value: this.formatMemory(vm.memory_gb) },
            { label: 'Generation', value: this.formatValue(vm.generation, '—') },
            { label: 'Configuration Version', value: this.formatValue(vm.version, '—') }
        ];

        const disks = Array.isArray(vm.disks) ? vm.disks : [];
        const networks = Array.isArray(vm.networks) ? vm.networks : [];
        const diskRows = disks.length
            ? disks.map(disk => `
                <tr>
                    <td>${this.escapeHtml(disk.name || 'Disk')}</td>
                    <td>${this.escapeHtml(disk.type || '—')}</td>
                    <td>${this.escapeHtml(this.formatDiskCapacity(disk))}</td>
                    <td>${this.escapeHtml(disk.path || disk.location || '—')}</td>
                </tr>
            `).join('')
            : `
                <tr class="vm-empty-row">
                    <td colspan="4">Disk information not available yet.</td>
                </tr>
            `;

        const networkRows = networks.length
            ? networks.map(adapter => `
                <tr>
                    <td>${this.escapeHtml(adapter.adapter_name || adapter.name || 'Adapter')}</td>
                    <td>${this.escapeHtml(this.extractAdapterAddresses(adapter))}</td>
                    <td>${this.escapeHtml(adapter.vlan || '—')}</td>
                    <td>${this.escapeHtml(adapter.network || adapter.virtual_switch || '—')}</td>
                </tr>
            `).join('')
            : `
                <tr class="vm-empty-row">
                    <td colspan="4">Network details not available yet.</td>
                </tr>
            `;

        const notesContent = this.escapeHtml(this.getNotesContent(vm));

        const tabs = [
            { id: 'hardware', label: 'VM Hardware' },
            { id: 'disks', label: 'Disks' },
            { id: 'networks', label: 'Networks' },
            { id: 'notes', label: 'Notes' }
        ];

        const actionButtons = this.buildVmActionButtons(vm);

        return `
            <div class="vm-header">
                <div class="vm-title-group">
                    <h1 class="page-title">${vm.name}</h1>
                    <span class="status ${meta.badgeClass}">${meta.label}</span>
                </div>
                <div class="vm-action-bar" role="toolbar" aria-label="Virtual machine controls">
                    ${actionButtons}
                </div>
                <div class="vm-action-feedback" role="status" aria-live="polite"></div>
            </div>

            <section class="vm-overview-panel surface-card" aria-label="Virtual machine overview">
                <div class="vm-overview-grid">
                    ${overviewItems.map(item => `
                        <div class="vm-overview-item">
                            <span class="vm-overview-label">${item.label}</span>
                            <span class="vm-overview-value">${this.escapeHtml(item.value)}</span>
                        </div>
                    `).join('')}
                </div>
            </section>

            <section class="vm-detail-tabs" aria-label="Virtual machine details">
                <div class="vm-tab-list" role="tablist" aria-label="Virtual machine detail tabs">
                    ${tabs.map((tab, index) => `
                        <button class="vm-tab ${index === 0 ? 'active' : ''}"
                            role="tab"
                            id="vm-tab-${tab.id}"
                            data-tab="${tab.id}"
                            aria-selected="${index === 0 ? 'true' : 'false'}"
                            tabindex="${index === 0 ? '0' : '-1'}">
                            ${tab.label}
                        </button>
                    `).join('')}
                </div>
                <div class="vm-tab-panels surface-card">
                    <div class="vm-tab-panel vm-tab-panel--hardware active" data-tab="hardware" role="tabpanel" aria-labelledby="vm-tab-hardware">
                        <div class="vm-hardware-grid">
                            ${hardwareItems.map(item => `
                                <div class="vm-hardware-item">
                                    <span class="vm-property-label">${item.label}</span>
                                    <span class="vm-property-value">${this.escapeHtml(item.value)}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    <div class="vm-tab-panel vm-tab-panel--table" data-tab="disks" role="tabpanel" aria-labelledby="vm-tab-disks" hidden>
                        <div class="vm-table-wrapper">
                            <table class="vm-data-table">
                                <thead>
                                    <tr>
                                        <th scope="col">Disk</th>
                                        <th scope="col">Type</th>
                                        <th scope="col">Capacity</th>
                                        <th scope="col">Location</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${diskRows}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="vm-tab-panel vm-tab-panel--table" data-tab="networks" role="tabpanel" aria-labelledby="vm-tab-networks" hidden>
                        <div class="vm-table-wrapper">
                            <table class="vm-data-table">
                                <thead>
                                    <tr>
                                        <th scope="col">Adapter</th>
                                        <th scope="col">IP Address</th>
                                        <th scope="col">VLAN</th>
                                        <th scope="col">Connected Network</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${networkRows}
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="vm-tab-panel vm-tab-panel--notes" data-tab="notes" role="tabpanel" aria-labelledby="vm-tab-notes" hidden>
                        <div class="vm-notes" aria-live="polite">
                            <div class="vm-notes-content" role="textbox" aria-readonly="true">${notesContent}</div>
                        </div>
                    </div>
                </div>
            </section>
        `;
    }

    init() {
        this.setupTabs();
        this.setupActions();
    }

    setupTabs() {
        const tabButtons = document.querySelectorAll('.vm-tab');
        const panels = document.querySelectorAll('.vm-tab-panel');

        if (!tabButtons.length || !panels.length) {
            return;
        }

        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const targetId = button.dataset.tab;

                tabButtons.forEach(tab => {
                    const isActive = tab === button;
                    tab.classList.toggle('active', isActive);
                    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
                    tab.setAttribute('tabindex', isActive ? '0' : '-1');
                });

                panels.forEach(panel => {
                    const isMatch = panel.dataset.tab === targetId;
                    panel.classList.toggle('active', isMatch);
                    panel.hidden = !isMatch;
                });
            });
        });
    }

    setupActions() {
        const actionBar = document.querySelector('.vm-action-bar');
        this.actionButtons = actionBar ? Array.from(actionBar.querySelectorAll('.vm-action-btn')) : [];
        this.feedbackElement = document.querySelector('.vm-action-feedback');
        this.actionInProgress = false;

        this.setActionFeedback('');

        this.updateActionButtonStates();

        if (!this.actionButtons || this.actionButtons.length === 0) {
            return;
        }

        this.actionButtons.forEach(button => {
            button.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();

                if (this.actionInProgress || !button || !button.dataset.action) {
                    return;
                }

                if (button.classList.contains('disabled') || button.hasAttribute('disabled')) {
                    return;
                }

                this.executeVmAction(button.dataset.action);
            });
        });
    }

    buildVmActionButtons(vm) {
        const availability = this.getActionAvailability(vm && vm.state);
        const actions = [
            { action: 'start', icon: '▶️', tooltip: 'Start', aria: 'Start virtual machine' },
            { action: 'shutdown', icon: '⏻', tooltip: 'Shut Down', aria: 'Shut down virtual machine' },
            { action: 'stop', icon: '⏹️', tooltip: 'Turn Off', aria: 'Stop (Turn Off) virtual machine' },
            { action: 'reset', icon: '🔄', tooltip: 'Reset', aria: 'Reset virtual machine' },
        ];

        return actions.map(({ action, icon, tooltip, aria }) => {
            const allowed = availability[action];
            const disabledAttr = allowed ? '' : 'disabled';
            const disabledClass = allowed ? '' : 'disabled';

            return `
                    <button type="button" class="vm-action-btn ${disabledClass}" data-action="${action}"
                        data-tooltip="${tooltip}" aria-label="${aria}" ${disabledAttr}>
                        <span aria-hidden="true">${icon}</span>
                    </button>
            `;
        }).join('');
    }

    getActionAvailability(state) {
        const normalized = typeof state === 'string' ? state.toLowerCase() : String(state || '').toLowerCase();
        const availability = {
            start: false,
            shutdown: false,
            stop: false,
            reset: false,
        };

        if (this.actionInProgress) {
            return availability;
        }

        if (normalized === 'running') {
            availability.shutdown = true;
            availability.stop = true;
            availability.reset = true;
        } else if (normalized === 'off') {
            availability.start = true;
        } else if (normalized === 'paused' || normalized === 'saved') {
            availability.start = true;
            availability.stop = true;
        }

        return availability;
    }

    updateActionButtonStates() {
        if (!this.actionButtons || this.actionButtons.length === 0) {
            return;
        }

        const availability = this.getActionAvailability(this.vmData && this.vmData.state);

        this.actionButtons.forEach(button => {
            const action = button.dataset.action;
            const allowed = Boolean(action && availability[action]);

            if (allowed) {
                button.classList.remove('disabled');
                button.removeAttribute('disabled');
            } else {
                button.classList.add('disabled');
                button.setAttribute('disabled', 'disabled');
            }
        });
    }

    setButtonsBusy(isBusy) {
        this.actionInProgress = Boolean(isBusy);
        this.updateActionButtonStates();
    }

    setActionFeedback(message, type = 'info') {
        if (!this.feedbackElement) {
            return;
        }

        this.feedbackElement.textContent = message || '';
        this.feedbackElement.classList.remove('success', 'error', 'info');
        if (message) {
            this.feedbackElement.classList.add(type);
        }
    }

    getActionLabel(action) {
        const labels = {
            start: 'start',
            shutdown: 'shut down',
            stop: 'stop',
            reset: 'reset',
        };
        return labels[action] || action || 'perform';
    }

    extractActionMessage(payload) {
        if (!payload) {
            return null;
        }

        if (typeof payload === 'string') {
            return payload;
        }

        if (payload.message && typeof payload.message === 'string') {
            return payload.message;
        }

        if (payload.detail) {
            if (typeof payload.detail === 'string') {
                return payload.detail;
            }
            if (payload.detail && typeof payload.detail.message === 'string') {
                return payload.detail.message;
            }
        }

        return null;
    }

    getDefaultSuccessMessage(action, vmName) {
        const name = vmName || (this.vmData && this.vmData.name) || 'virtual machine';
        switch (action) {
            case 'start':
                return `Start command accepted for VM ${name}.`;
            case 'shutdown':
                return `Shutdown command accepted for VM ${name}.`;
            case 'stop':
                return `Stop command accepted for VM ${name}.`;
            case 'reset':
                return `Reset command accepted for VM ${name}.`;
            default:
                return `Command accepted for VM ${name}.`;
        }
    }

    estimateNextState(action) {
        switch (action) {
            case 'start':
            case 'reset':
                return 'Starting';
            case 'shutdown':
            case 'stop':
                return 'Stopping';
            default:
                return this.vmData && this.vmData.state ? this.vmData.state : 'Unknown';
        }
    }

    async executeVmAction(action) {
        if (!this.vmData || !this.vmData.name) {
            return;
        }

        const host = this.vmHost || this.vmData.host || this.data.host;
        if (!host) {
            return;
        }

        const encodedHost = encodeURIComponent(host);
        const encodedVm = encodeURIComponent(this.vmData.name);
        const endpoint = `/api/v1/vms/${encodedHost}/${encodedVm}/${action}`;

        this.setButtonsBusy(true);
        this.setActionFeedback(`Sending ${this.getActionLabel(action)} request...`, 'info');

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                credentials: 'same-origin',
            });

            let payload = null;
            try {
                payload = await response.json();
            } catch (err) {
                payload = null;
            }

            if (response.ok) {
                const message = this.extractActionMessage(payload)
                    || this.getDefaultSuccessMessage(action, this.vmData.name);
                this.setActionFeedback(message, 'success');

                const nextState = this.estimateNextState(action);
                if (this.vmData) {
                    this.vmData.state = nextState;
                }
                this.updateActionButtonStates();

                setTimeout(() => {
                    viewManager.switchView('vm', { name: this.vmData.name, host });
                }, 400);
            } else {
                const detail = this.extractActionMessage(payload) || response.statusText || 'Request failed';
                this.setActionFeedback(`Unable to ${this.getActionLabel(action)} VM: ${detail}`, 'error');
            }
        } catch (error) {
            console.error('VM action error:', error);
            this.setActionFeedback(`Failed to ${this.getActionLabel(action)} VM: ${error.message}`, 'error');
        } finally {
            this.setButtonsBusy(false);
        }
    }

    formatOsFamily(vm) {
        if (vm.os_name) {
            return vm.os_name;
        }

        if (!vm.os_family) {
            return 'Unknown';
        }

        const family = String(vm.os_family).toLowerCase();
        if (family.includes('windows')) {
            return 'Windows';
        }
        if (family.includes('linux')) {
            return 'Linux';
        }
        return this.formatValue(vm.os_family, 'Unknown');
    }

    formatMemory(memoryGb) {
        const value = Number(memoryGb);
        if (Number.isFinite(value) && value > 0) {
            return `${value.toFixed(2)} GB`;
        }
        if (Number.isFinite(value) && value === 0) {
            return '0 GB';
        }
        return '—';
    }

    formatDiskCapacity(disk) {
        if (disk && typeof disk.capacity !== 'undefined') {
            return `${disk.capacity}`;
        }
        if (disk && typeof disk.size_gb !== 'undefined') {
            const size = Number(disk.size_gb);
            return Number.isFinite(size) ? `${size.toFixed(2)} GB` : `${disk.size_gb}`;
        }
        if (disk && typeof disk.size !== 'undefined') {
            return `${disk.size}`;
        }
        return '—';
    }

    formatHostname(hostname) {
        if (!hostname) {
            return 'Unknown host';
        }
        const hostText = String(hostname).trim();
        if (!hostText) {
            return 'Unknown host';
        }
        const dotIndex = hostText.indexOf('.');
        return dotIndex === -1 ? hostText : hostText.slice(0, dotIndex);
    }

    findVm(inventory, vmName, requestedHost) {
        if (!inventory) {
            return null;
        }

        const vms = Array.isArray(inventory.vms) ? inventory.vms : [];
        if (vms.length === 0) {
            return null;
        }

        const normalizedName = String(vmName || '').toLowerCase();
        const normalizedHost = requestedHost ? String(requestedHost).toLowerCase() : null;

        if (normalizedHost) {
            const hostMatch = vms.find(vm => {
                if (!vm) {
                    return false;
                }
                const hostValue = String(vm.host || '').toLowerCase();
                const nameValue = String(vm.name || '').toLowerCase();
                return nameValue === normalizedName && hostValue === normalizedHost;
            });
            if (hostMatch) {
                return hostMatch;
            }
        }

        return vms.find(vm => {
            if (!vm) {
                return false;
            }
            return String(vm.name || '').toLowerCase() === normalizedName;
        }) || null;
    }

    findHost(inventory, hostname) {
        if (!inventory || !hostname) {
            return null;
        }
        const hosts = Array.isArray(inventory.hosts) ? inventory.hosts : [];
        return hosts.find(host => host && host.hostname === hostname) || null;
    }

    formatClusterState(vm, hostInfo) {
        const rawClustered = vm.clustered ?? vm.is_clustered ?? vm.vm_clustered;
        if (typeof rawClustered !== 'undefined' && rawClustered !== null) {
            if (typeof rawClustered === 'boolean') {
                if (rawClustered) {
                    const clusterName = hostInfo && hostInfo.cluster ? ` (${hostInfo.cluster})` : '';
                    return `Yes${clusterName}`;
                }
                return 'No';
            }

            const normalized = String(rawClustered).trim().toLowerCase();
            if (['yes', 'true', '1'].includes(normalized)) {
                const clusterName = hostInfo && hostInfo.cluster ? ` (${hostInfo.cluster})` : '';
                return `Yes${clusterName}`;
            }
            if (['no', 'false', '0'].includes(normalized)) {
                return 'No';
            }
            if (normalized.length > 0) {
                return this.formatValue(rawClustered, 'Unknown');
            }
        }

        if (hostInfo && hostInfo.cluster) {
            return `Yes (${hostInfo.cluster})`;
        }
        if (hostInfo) {
            return 'No';
        }
        return 'Unknown';
    }

    extractIpAddresses(vm) {
        if (Array.isArray(vm.ip_addresses) && vm.ip_addresses.length > 0) {
            return vm.ip_addresses.join(', ');
        }
        if (vm.ip_address) {
            return vm.ip_address;
        }
        return 'Not available';
    }

    extractAdapterAddresses(adapter) {
        if (!adapter) {
            return '—';
        }
        if (Array.isArray(adapter.ip_addresses) && adapter.ip_addresses.length > 0) {
            return adapter.ip_addresses.join(', ');
        }
        if (adapter.ip_address) {
            return adapter.ip_address;
        }
        return '—';
    }

    getNotesContent(vm) {
        if (Array.isArray(vm.notes) && vm.notes.length > 0) {
            return vm.notes.join('\n');
        }
        if (typeof vm.notes === 'string' && vm.notes.trim().length > 0) {
            return vm.notes;
        }
        return 'No notes have been recorded for this virtual machine.';
    }

    formatValue(value, fallback = '—') {
        if (value === null || typeof value === 'undefined') {
            return fallback;
        }
        const text = String(value).trim();
        return text.length > 0 ? text : fallback;
    }

    formatDate(value) {
        if (!value) {
            return 'Not available';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return 'Not available';
        }
        return date.toLocaleString();
    }

    escapeHtml(value) {
        if (value === null || typeof value === 'undefined') {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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

            <div class="view-section surface-card">
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
