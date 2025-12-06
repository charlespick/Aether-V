// View System - Dynamic content management
const { renderDefaultIcon: renderIconDefault } = window.iconUtils;

function icon(name, options = {}) {
    return renderIconDefault(name, options);
}
class ViewManager {
    constructor() {
        this.currentView = null;
        this.viewContainer = null;
        this.views = new Map();
        this.state = {};
        this.currentViewName = null;
        this.currentViewData = {};
        this.historyInitialized = false;
        this.currentRouteUrl =
            typeof window !== 'undefined' && window.location
                ? `${window.location.pathname}${window.location.search}`
                : '/';
        this.baseDocumentTitle =
            typeof document !== 'undefined' && document.title
                ? document.title
                : 'Aether-V — Dashboard';
        this.appName = this.extractAppName(this.baseDocumentTitle);
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

    extractAppName(title) {
        if (!title) {
            return 'Aether-V';
        }
        const text = String(title);
        const parts = text.split('—');
        if (parts.length > 1) {
            const candidate = parts[0].trim();
            return candidate || 'Aether-V';
        }
        const trimmed = text.trim();
        return trimmed || 'Aether-V';
    }

    setAppName(name) {
        if (!name) {
            return;
        }
        const trimmed = String(name).trim();
        if (!trimmed) {
            return;
        }
        this.appName = trimmed;
        if (typeof document === 'undefined') {
            return;
        }

        if (this.currentViewName) {
            const updatedTitle = this.buildViewTitle(this.currentViewName, this.currentViewData);
            if (updatedTitle) {
                document.title = updatedTitle;
            }
        } else {
            document.title = `${this.appName} — Dashboard`;
        }
    }

    buildViewUrl(viewName, viewData = {}) {
        switch (viewName) {
            case 'overview':
                return '/';
            case 'cluster': {
                const clusterName = viewData && viewData.name ? String(viewData.name) : '';
                if (!clusterName) {
                    return null;
                }
                return `/cluster/${encodeURIComponent(clusterName)}`;
            }
            case 'host': {
                const hostname = viewData && viewData.hostname ? String(viewData.hostname) : '';
                if (!hostname) {
                    return null;
                }
                return `/host/${encodeURIComponent(hostname)}`;
            }
            case 'vm': {
                const vmId = viewData && viewData.id ? String(viewData.id) : '';
                if (!vmId) {
                    return null;
                }
                return `/virtual-machine/${encodeURIComponent(vmId)}`;
            }
            case 'disconnected-hosts':
                return '/disconnected-hosts';
            default:
                return '/';
        }
    }

    buildViewTitle(viewName, viewData = {}) {
        const appName = this.appName || 'Aether-V';
        switch (viewName) {
            case 'cluster': {
                const clusterName = viewData && viewData.name ? String(viewData.name) : '';
                return clusterName
                    ? `${appName} — Cluster: ${clusterName}`
                    : `${appName} — Cluster`;
            }
            case 'host': {
                const hostname = viewData && viewData.hostname ? String(viewData.hostname) : '';
                const shortName = formatHostnamePrefix(hostname) || hostname;
                return hostname
                    ? `${appName} — Host: ${shortName}`
                    : `${appName} — Host`;
            }
            case 'vm': {
                const vmName = viewData && viewData.name ? String(viewData.name) : '';
                return vmName ? `${appName} — VM: ${vmName}` : `${appName} — Virtual Machine`;
            }
            case 'disconnected-hosts':
                return `${appName} — Disconnected Hosts`;
            case 'overview':
                return `${appName} — Overview`;
            default:
                return `${appName} — Dashboard`;
        }
    }

    updatePageMetadata(viewName, viewData = {}, options = {}) {
        const { skipHistory = false, replaceHistory = false } = options || {};

        if (typeof document !== 'undefined') {
            const nextTitle = this.buildViewTitle(viewName, viewData);
            if (nextTitle) {
                document.title = nextTitle;
            }
        }

        if (
            skipHistory ||
            typeof window === 'undefined' ||
            !window.history ||
            typeof window.history.pushState !== 'function'
        ) {
            return;
        }

        const url = this.buildViewUrl(viewName, viewData);
        if (!url) {
            return;
        }

        const currentUrl = `${window.location.pathname}${window.location.search}`;
        const state = { viewName, data: { ...viewData } };

        if (replaceHistory || !this.historyInitialized) {
            window.history.replaceState(state, '', url);
            this.historyInitialized = true;
        } else if (url !== currentUrl) {
            window.history.pushState(state, '', url);
        } else {
            window.history.replaceState(state, '', url);
        }

        this.currentRouteUrl = url;
    }

    safeDecode(value) {
        if (typeof value !== 'string') {
            return value;
        }
        try {
            return decodeURIComponent(value);
        } catch (error) {
            console.warn('Failed to decode route segment:', value, error);
            return value;
        }
    }

    resolveRouteFromLocation(locationLike) {
        const location = locationLike || (typeof window !== 'undefined' ? window.location : null);
        if (!location) {
            return { viewName: 'overview', data: {}, matched: true };
        }

        const pathname = location.pathname || '/';
        const search = location.search || '';
        const cleaned = pathname.replace(/^\/+|\/+$/g, '');
        const segments = cleaned ? cleaned.split('/') : [];
        const params = new URLSearchParams(search);

        if (segments.length === 0) {
            return { viewName: 'overview', data: {}, matched: true };
        }

        const [section, ...rest] = segments;
        const remainder = rest.length > 0 ? rest.join('/') : '';

        if (section === 'cluster' && remainder) {
            return {
                viewName: 'cluster',
                data: { name: this.safeDecode(remainder) },
                matched: true,
            };
        }

        if (section === 'host' && remainder) {
            return {
                viewName: 'host',
                data: { hostname: this.safeDecode(remainder) },
                matched: true,
            };
        }

        if (section === 'virtual-machine' && remainder) {
            const data = { id: this.safeDecode(remainder) };
            return { viewName: 'vm', data, matched: true };
        }

        if (section === 'disconnected-hosts') {
            return { viewName: 'disconnected-hosts', data: {}, matched: true };
        }

        return { viewName: 'overview', data: {}, matched: false };
    }

    handleAnchorNavigation(event, viewName, data = {}) {
        if (!event) {
            this.switchView(viewName, data);
            return false;
        }

        if (event.defaultPrevented) {
            return false;
        }

        const isModifiedClick =
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1;

        if (isModifiedClick) {
            return true;
        }

        event.preventDefault();
        this.switchView(viewName, data);
        return false;
    }

    async switchView(viewName, data = {}, options = {}) {
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
        this.currentViewName = viewName;
        this.currentViewData = { ...data };
        this.updateNavigation(viewName, this.currentViewData);

        if (typeof window.applyProvisioningAvailability === 'function') {
            window.applyProvisioningAvailability(window.agentDeploymentState);
        }

        this.updatePageMetadata(viewName, this.currentViewData, options);
        return this.currentView;
    }

    updateNavigation(viewName, viewData = {}) {
        // Remove active from all nav items
        document.querySelectorAll('.nav-item, .sub-item, .vm-item').forEach(item => {
            item.classList.remove('active');
        });

        const escapeForSelector = (value) => {
            if (typeof value !== 'string') {
                return '';
            }
            if (window.CSS && typeof window.CSS.escape === 'function') {
                return window.CSS.escape(value);
            }
            // Polyfill for CSS.escape from https://developer.mozilla.org/en-US/docs/Web/API/CSS/escape#polyfill
            // This polyfill escapes all characters that could cause issues in CSS selectors.
            // Copyright Mathias Bynens <https://mathiasbynens.be/>
            // Licensed under the MIT license.
            var string = String(value);
            var length = string.length;
            var index = -1;
            var codeUnit;
            var result = '';
            var firstCodeUnit = string.charCodeAt(0);
            while (++index < length) {
                codeUnit = string.charCodeAt(index);
                // Note: there’s no need to special-case astral symbols, surrogate
                // pairs, or lone surrogates.
                if (
                    // If the character is NULL (U+0000), then the REPLACEMENT CHARACTER (U+FFFD).
                    codeUnit == 0x0000
                ) {
                    result += '\uFFFD';
                    continue;
                }
                if (
                    // If the character is in the range [1-31] (U+0001 to U+001F) or U+007F, escape.
                    (codeUnit >= 0x0001 && codeUnit <= 0x001F) ||
                    codeUnit == 0x007F ||
                    // If the character is the first character and is a digit, escape.
                    (index == 0 && codeUnit >= 0x0030 && codeUnit <= 0x0039) ||
                    // If the character is the second character and is a digit and the first character is a hyphen, escape.
                    (index == 1 && codeUnit >= 0x0030 && codeUnit <= 0x0039 && firstCodeUnit == 0x002D)
                ) {
                    result += '\\' + codeUnit.toString(16) + ' ';
                    continue;
                }
                if (
                    // If the character is ASCII and not a letter, digit, or underscore, escape.
                    codeUnit >= 0x0080 ||
                    codeUnit == 0x002D || // hyphen
                    codeUnit == 0x005F || // underscore
                    (codeUnit >= 0x0030 && codeUnit <= 0x0039) || // 0-9
                    (codeUnit >= 0x0041 && codeUnit <= 0x005A) || // A-Z
                    (codeUnit >= 0x0061 && codeUnit <= 0x007A)    // a-z
                ) {
                    // No need to escape
                    result += string.charAt(index);
                } else {
                    result += '\\' + string.charAt(index);
                }
            }
            return result;
        };

        let navItem = null;

        if (viewName === 'overview' || viewName === 'disconnected-hosts') {
            navItem = document.querySelector(`[data-view="${viewName}"]`);
        } else if (viewName === 'cluster' && viewData?.name) {
            const selector = escapeForSelector(viewData.name);
            navItem = document.querySelector(`.nav-item.group-header[data-nav-type="cluster"][data-cluster-name="${selector}"]`);
        } else if (viewName === 'host' && viewData?.hostname) {
            const selector = escapeForSelector(viewData.hostname);
            navItem = document.querySelector(`.sub-item.group-header[data-nav-type="host"][data-hostname="${selector}"]`);
        } else if (viewName === 'vm' && viewData?.id) {
            const idSelector = escapeForSelector(viewData.id);
            navItem = document.querySelector(`.vm-item[data-nav-type="vm"][data-vm-id="${idSelector}"]`);
        }

        if (navItem) {
            navItem.classList.add('active');

            const navGroup = navItem.closest('.nav-group');
            if (navGroup) {
                navGroup.classList.add('expanded');

                if (navGroup.dataset && navGroup.dataset.host) {
                    const clusterGroup = navGroup.closest('.nav-group[data-cluster]');
                    if (clusterGroup) {
                        clusterGroup.classList.add('expanded');
                    }
                }
            }

            const hostGroup = navItem.closest('.nav-group[data-host]');
            if (hostGroup) {
                hostGroup.classList.add('expanded');
                const clusterGroup = hostGroup.closest('.nav-group[data-cluster]');
                if (clusterGroup) {
                    clusterGroup.classList.add('expanded');
                }
            }
        }

        this.currentViewName = viewName;
        this.currentViewData = { ...viewData };
    }

    refreshNavigationState() {
        if (this.currentViewName) {
            this.updateNavigation(this.currentViewName, this.currentViewData);
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

function sanitizeHtml(value) {
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

function escapeJsString(value) {
    if (value === null || typeof value === 'undefined') {
        return '';
    }
    return String(value)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');
}

function formatMemoryAmount(memory) {
    if (memory === null || typeof memory === 'undefined') {
        return null;
    }
    const parsed = Number(memory);
    if (!Number.isFinite(parsed)) {
        return null;
    }
    return `${parsed.toFixed(2)} GB`;
}

function resolveVmMemoryValue(vm) {
    const assigned = Number(vm?.memory_gb);
    const startup = Number(vm?.memory_startup_gb);

    if (Number.isFinite(assigned) && assigned > 0) {
        return assigned;
    }

    if (Number.isFinite(startup) && startup > 0) {
        return startup;
    }

    if (Number.isFinite(assigned)) {
        return assigned;
    }

    return null;
}

function formatVmMemoryDisplay(vm) {
    const memoryValue = resolveVmMemoryValue(vm);
    if (memoryValue === null) {
        return '—';
    }

    let display = formatMemoryAmount(memoryValue) || '—';
    if (vm?.dynamic_memory_enabled) {
        display += ' (dynamic)';
    }

    return display;
}

function formatCpuCount(cpu) {
    if (cpu === null || typeof cpu === 'undefined') {
        return '—';
    }
    const parsed = Number(cpu);
    if (!Number.isFinite(parsed)) {
        return '—';
    }
    return parsed.toString();
}

function formatHostnamePrefix(hostname) {
    if (hostname === null || typeof hostname === 'undefined') {
        return '';
    }
    const trimmed = String(hostname).trim();
    if (!trimmed) {
        return '';
    }
    return trimmed.split('.')[0];
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
                            <div class="empty-icon">${icon('warning', { className: 'status-warning', size: 48 })}</div>
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
                                    ${icon('warning', { className: 'action-icon status-warning', size: 24 })}
                                    <span>View Disconnected Hosts</span>
                                </button>
                            </div>
                        ` : `
                            <div class="empty-icon">${icon('host', { className: 'status-muted', size: 48 })}</div>
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
                        ${icon('add_circle', { className: 'action-icon', size: 24 })}
                        <span>Create VM</span>
                    </button>
                    <button class="action-btn" onclick="overlayManager.open('settings')">
                        ${icon('settings', { className: 'action-icon', size: 24 })}
                        <span>Settings</span>
                    </button>
                    <button class="action-btn" onclick="refreshInventory()">
                        ${icon('autorenew', { className: 'action-icon', size: 24 })}
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

            <div class="view-section">
                <div class="view-section-label">Virtual Machines</div>
                <div class="surface-card vm-table-card">
                    ${this.renderVmTable(clusterVMs)}
                </div>
            </div>

            <div class="view-section surface-card">
                <div class="section-header">
                    <h2>Cluster Resources</h2>
                </div>
                <div class="resource-summary">
                    <p>Total CPU Cores: ${this.calculateTotalCPU(clusterHosts)}</p>
                    <p>Total Memory: ${this.calculateTotalMemory(clusterHosts)} GB</p>
                </div>
            </div>
        `;
    }

    renderHostCards(hosts) {
        if (hosts.length === 0) {
            return '<p class="empty">No hosts configured</p>';
        }

        return hosts.map(host => {
            const hostname = host.hostname || 'Unknown Host';
            const hostnamePrefix = formatHostnamePrefix(hostname) || hostname;
            const displayName = sanitizeHtml(hostnamePrefix);
            const tooltip = sanitizeHtml(hostname);
            const targetHost = escapeJsString(host.hostname || hostnamePrefix);
            return `
            <div class="host-card" onclick="viewManager.switchView('host', { hostname: '${targetHost}' })">
                <div class="host-card-header">
                    ${icon('host', { className: 'host-icon status-muted', size: 28 })}
                    <span class="host-name" title="${tooltip}">${displayName}</span>
                </div>
                <div class="host-card-status">
                    <span class="status ${host.connected ? 'connected' : 'disconnected'}">
                        ${host.connected ? 'Connected' : 'Disconnected'}
                    </span>
                </div>
            </div>
        `;
        }).join('');
    }

    renderVmTable(vms) {
        if (!Array.isArray(vms) || vms.length === 0) {
            return '<p class="empty">No virtual machines</p>';
        }

        const rows = vms.map(vm => {
            const meta = getVmStateMeta(vm.state);
            const vmName = vm.name || 'Virtual Machine';
            const vmId = vm.id || '';
            const hostName = vm.host || '';
            const hostDisplay = formatHostnamePrefix(hostName);
            const safeHostDisplay = hostDisplay ? sanitizeHtml(hostDisplay) : '—';
            const safeHostTitle = hostName ? sanitizeHtml(hostName) : '';
            return `
                <tr class="vm-table-row">
                    <td>
                        <button type="button" class="vm-table-link"
                            onclick="viewManager.switchView('vm', { id: '${escapeJsString(vmId)}', name: '${escapeJsString(vmName)}', host: '${escapeJsString(hostName)}' })">
                            <span class="vm-status-dot ${meta.dotClass}"></span>
                            <span class="vm-name-text">${sanitizeHtml(vmName)}</span>
                        </button>
                    </td>
                    <td><span class="status ${meta.badgeClass}">${sanitizeHtml(meta.label)}</span></td>
                    <td>${sanitizeHtml(formatCpuCount(vm.cpu_cores))}</td>
                    <td>${sanitizeHtml(formatVmMemoryDisplay(vm))}</td>
                    <td>${hostDisplay ? `<span class="vm-table-host" title="${safeHostTitle}">${safeHostDisplay}</span>` : '<span class="vm-table-host">—</span>'}</td>
                </tr>
            `;
        }).join('');

        return `
            <div class="vm-table-wrapper">
                <table class="vm-data-table">
                    <thead>
                        <tr>
                            <th scope="col">Name</th>
                            <th scope="col">Status</th>
                            <th scope="col">vCPU</th>
                            <th scope="col">Memory</th>
                            <th scope="col">Host</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
    }

    calculateTotalCPU(hosts) {
        return hosts.reduce((sum, host) => sum + (host.total_cpu_cores || 0), 0);
    }

    calculateTotalMemory(hosts) {
        const total = hosts.reduce((sum, host) => sum + (host.total_memory_gb || 0), 0);
        return total.toFixed(2);
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
        const resolvedHostname = host?.hostname || hostname;
        const shortHostname = formatHostnamePrefix(resolvedHostname) || resolvedHostname;
        const displayHostname = sanitizeHtml(shortHostname);
        const fullHostname = sanitizeHtml(resolvedHostname);
        const hostVMs = inventory.vms.filter(vm => vm.host === hostname);
        const managingCluster = this.buildManagingClusterValue(host);

        return `
            <h1 class="page-title">${displayHostname}</h1>

            <div class="view-section surface-card">
                <div class="section-header">
                    <h2>Host Information</h2>
                </div>
                <div class="vm-overview-grid host-info-grid">
                    <div class="vm-overview-item">
                        <span class="vm-overview-label">Full Host Name</span>
                        <span class="vm-overview-value">${fullHostname}</span>
                    </div>
                    <div class="vm-overview-item">
                        <span class="vm-overview-label">Status</span>
                        <span class="status ${host?.connected ? 'connected' : 'disconnected'}">
                            ${host?.connected ? 'Connected' : 'Disconnected'}
                        </span>
                    </div>
                    <div class="vm-overview-item">
                        <span class="vm-overview-label">Last Seen</span>
                        <span class="vm-overview-value">${host?.last_seen ? new Date(host.last_seen).toLocaleString() : 'Never'}</span>
                    </div>
                    <div class="vm-overview-item">
                        <span class="vm-overview-label">VM Count</span>
                        <span class="vm-overview-value">${hostVMs.length}</span>
                    </div>
                    <div class="vm-overview-item">
                        <span class="vm-overview-label">Managing Cluster</span>
                        <span class="vm-overview-value">${managingCluster}</span>
                    </div>
                </div>
            </div>

            <div class="view-section">
                <div class="view-section-label">Virtual Machines</div>
                <div class="surface-card vm-table-card">
                    ${this.renderVmTable(hostVMs, hostname)}
                </div>
            </div>
        `;
    }

    buildManagingClusterValue(host) {
        const clusterName = host && typeof host.cluster !== 'undefined' ? host.cluster : null;
        if (clusterName === null || typeof clusterName === 'undefined') {
            return '—';
        }

        const text = String(clusterName).trim();
        if (!text) {
            return '—';
        }

        const safeClusterName = sanitizeHtml(text);
        const clusterNameJs = escapeJsString(text);
        const clusterHref = `/cluster/${encodeURIComponent(text)}`;
        return `<a href="${clusterHref}" class="vm-link" onclick="return viewManager.handleAnchorNavigation(event, 'cluster', { name: '${clusterNameJs}' });">${safeClusterName}</a>`;
    }

    renderVmTable(vms, fallbackHost = '') {
        if (!Array.isArray(vms) || vms.length === 0) {
            return '<p class="empty">No VMs on this host</p>';
        }

        const rows = vms.map(vm => {
            const meta = getVmStateMeta(vm.state);
            const vmName = vm.name || 'Virtual Machine';
            const vmId = vm.id || '';
            const hostName = vm.host || fallbackHost || '';
            return `
                <tr class="vm-table-row">
                    <td>
                        <button type="button" class="vm-table-link"
                            onclick="viewManager.switchView('vm', { id: '${escapeJsString(vmId)}', name: '${escapeJsString(vmName)}', host: '${escapeJsString(hostName)}' })">
                            <span class="vm-status-dot ${meta.dotClass}"></span>
                            <span class="vm-name-text">${sanitizeHtml(vmName)}</span>
                        </button>
                    </td>
                    <td><span class="status ${meta.badgeClass}">${sanitizeHtml(meta.label)}</span></td>
                    <td>${sanitizeHtml(formatCpuCount(vm.cpu_cores))}</td>
                    <td>${sanitizeHtml(formatVmMemoryDisplay(vm))}</td>
                </tr>
            `;
        }).join('');

        return `
            <div class="vm-table-wrapper">
                <table class="vm-data-table">
                    <thead>
                        <tr>
                            <th scope="col">Name</th>
                            <th scope="col">Status</th>
                            <th scope="col">vCPU</th>
                            <th scope="col">Memory</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
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

// VM View
class VMView extends BaseView {
    async render() {
        const vmId = this.data.id || '';
        
        if (!vmId) {
            return `
                <h1 class="page-title">VM Not Found</h1>
                <p class="empty">Virtual machine ID not provided</p>
            `;
        }
        
        const vm = await this.fetchVmById(vmId);

        if (!vm) {
            return `
                <h1 class="page-title">VM Not Found</h1>
                <p class="empty">Virtual machine with ID "${vmId}" not found</p>
            `;
        }

        this.vmData = vm;
        this.vmHost = vm.host;
        
        // Fetch full inventory for host/cluster context
        const inventory = await this.fetchInventory();
        this.lastInventory = inventory;

        const meta = getVmStateMeta(vm.state);
        const osName = this.formatOsFamily(vm);
        const hostInfo = this.findHost(inventory, vm.host);
        const hostOverview = this.buildHostOverviewValue(vm.host);
        const clusterOverview = this.buildClusterOverviewValue(vm, hostInfo);
        const memoryItems = this.buildMemoryHardwareItems(vm);
        const overviewItems = [
            { label: 'Hyper-V Host', value: hostOverview.value, isHtml: hostOverview.isHtml },
            { label: 'IP Address(es)', value: this.extractIpAddresses(vm) },
            { label: 'Operating System', value: osName },
            { label: 'Clustered', value: clusterOverview.value, isHtml: clusterOverview.isHtml },
            { label: 'Created', value: this.formatDate(vm.created_at) }
        ];

        const hardwareItems = [
            { label: 'CPU Cores', value: this.formatValue(vm.cpu_cores, '—') },
            ...memoryItems,
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
                    <td class="vm-resource-actions">
                        <button type="button" class="resource-menu-btn" 
                            data-resource-type="disk" 
                            data-resource-id="${this.escapeHtml(disk.id || '')}"
                            aria-label="Disk actions"
                            title="Actions">
                            ${icon('more_vert', { size: 20 })}
                        </button>
                    </td>
                </tr>
            `).join('')
            : `
                <tr class="vm-empty-row">
                    <td colspan="5">Disk information not available yet.</td>
                </tr>
            `;

        const networkRows = networks.length
            ? networks.map(adapter => {
                // Determine network display value
                let networkDisplay = '—';
                if (adapter.network_name) {
                    networkDisplay = adapter.network_name;
                } else if (adapter.virtual_switch && adapter.vlan) {
                    networkDisplay = `${adapter.virtual_switch}/${adapter.vlan}`;
                } else if (adapter.vlan) {
                    networkDisplay = `VLAN ${adapter.vlan}`;
                } else if (adapter.virtual_switch) {
                    networkDisplay = adapter.virtual_switch;
                }
                
                return `
                <tr>
                    <td>${this.escapeHtml(adapter.adapter_name || adapter.name || 'Adapter')}</td>
                    <td>${this.escapeHtml(this.extractAdapterAddresses(adapter))}</td>
                    <td>${this.escapeHtml(networkDisplay)}</td>
                    <td class="vm-resource-actions">
                        <button type="button" class="resource-menu-btn" 
                            data-resource-type="nic" 
                            data-resource-id="${this.escapeHtml(adapter.id || '')}"
                            aria-label="Network adapter actions"
                            title="Actions">
                            ${icon('more_vert', { size: 20 })}
                        </button>
                    </td>
                </tr>
                `;
            }).join('')
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
            </div>

            <section class="vm-overview-panel surface-card" aria-label="Virtual machine overview">
                <div class="section-header">
                    <h2>Virtual Machine Information</h2>
                </div>
                <div class="vm-overview-grid">
                    ${overviewItems.map(item => `
                        <div class="vm-overview-item">
                            <span class="vm-overview-label">${item.label}</span>
                            <span class="vm-overview-value">${item.isHtml ? item.value : this.escapeHtml(item.value)}</span>
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
                                        <th scope="col" class="vm-resource-actions-header">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${diskRows}
                                </tbody>
                            </table>
                        </div>
                        <div class="vm-tab-actions">
                            <button class="action-btn" data-action="add-disk" onclick="overlayManager.open('disk-create', { vm_id: '${this.escapeHtml(vm.id)}', vm_name: '${this.escapeHtml(vm.name)}', host: '${this.escapeHtml(vm.host)}' })">
                                ${icon('add_circle', { className: 'action-icon', size: 24 })}
                                <span>Add Disk</span>
                            </button>
                        </div>
                    </div>
                    <div class="vm-tab-panel vm-tab-panel--table" data-tab="networks" role="tabpanel" aria-labelledby="vm-tab-networks" hidden>
                        <div class="vm-table-wrapper">
                            <table class="vm-data-table">
                                <thead>
                                    <tr>
                                        <th scope="col">Adapter</th>
                                        <th scope="col">IP Address</th>
                                        <th scope="col">Network</th>
                                        <th scope="col" class="vm-resource-actions-header">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${networkRows}
                                </tbody>
                            </table>
                        </div>
                        <div class="vm-tab-actions">
                            <button class="action-btn" data-action="add-nic" onclick="overlayManager.open('nic-create', { vm_id: '${this.escapeHtml(vm.id)}', vm_name: '${this.escapeHtml(vm.name)}', host: '${this.escapeHtml(vm.host)}' })">
                                ${icon('add_circle', { className: 'action-icon', size: 24 })}
                                <span>Add Network Adapter</span>
                            </button>
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
        this.setupResourceMenus();
    }

    cleanup() {
        this.destroyActionConfirmation(true);
        this.hideActionToast(true);
        this.cleanupResourceMenus();
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
        this.actionInProgress = false;
        this.toastHideTimer = null;
        this.actionToastElement = null;
        this.confirmationElement = null;
        this.activeConfirmButton = null;
        this.activeConfirmAction = null;
        this.boundConfirmOutsideHandler = null;
        this.boundConfirmKeyHandler = null;
        this.boundConfirmRepositionHandler = null;

        this.boundActionHandler = (event) => this.handleActionButtonClick(event);

        this.updateActionButtonStates();

        if (!this.actionButtons || this.actionButtons.length === 0) {
            return;
        }

        this.actionButtons.forEach(button => {
            button.addEventListener('click', this.boundActionHandler);
        });
    }

    handleActionButtonClick(event) {
        if (!event) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();

        const button = event.currentTarget;

        if (this.actionInProgress || !button || !button.dataset.action) {
            return;
        }

        if (button.classList.contains('disabled') || button.hasAttribute('disabled')) {
            return;
        }

        const action = button.dataset.action;
        
        // Handle edit action - open VM edit overlay
        if (action === 'edit') {
            overlayManager.open('vm-edit', { 
                vm_id: this.vmData.id,
                vm_name: this.vmData.name, 
                host: this.vmData.host,
                vm_data: this.vmData  // Pass actual VM data for pre-filling
            });
            return;
        }

        if (this.requiresConfirmation(action)) {
            if (this.activeConfirmButton === button && this.activeConfirmAction === action) {
                this.destroyActionConfirmation();
            } else {
                this.showActionConfirmation(button, action);
            }
            return;
        }

        this.executeVmAction(action);
    }

    requiresConfirmation(action) {
        if (!action) {
            return false;
        }
        const normalized = String(action).toLowerCase();
        return ['stop', 'shutdown', 'reset', 'delete'].includes(normalized);
    }

    getActionConfirmationCopy(action) {
        const vmName = (this.vmData && this.vmData.name) ? this.vmData.name : 'this virtual machine';
        const normalized = String(action || '').toLowerCase();

        if (normalized === 'shutdown') {
            return {
                title: 'Confirm shut down',
                message: `Shut down ${vmName}? This requests a graceful shutdown from the guest operating system.`,
                confirmLabel: 'Shut down',
            };
        }

        if (normalized === 'stop') {
            return {
                title: 'Confirm turn off',
                message: `Turn off ${vmName}? This immediately powers off the VM and may cause data loss.`,
                confirmLabel: 'Turn off',
            };
        }

        if (normalized === 'reset') {
            return {
                title: 'Confirm reset',
                message: `Reset ${vmName}? This power cycles the VM and will interrupt any running processes.`,
                confirmLabel: 'Reset',
            };
        }

        if (normalized === 'delete') {
            return {
                title: 'Confirm delete',
                message: `Delete ${vmName}? This permanently removes the VM registration and disks from the host.`,
                confirmLabel: 'Delete',
            };
        }

        return {
            title: 'Confirm action',
            message: `Proceed with ${normalized || 'this'} action on ${vmName}?`,
            confirmLabel: 'Confirm',
        };
    }

    showActionConfirmation(button, action) {
        if (!button) {
            return;
        }

        if (this.confirmationElement && this.confirmationElement.isConnected) {
            this.destroyActionConfirmation(true);
        }

        const copy = this.getActionConfirmationCopy(action);
        const overlay = document.createElement('div');
        overlay.className = 'vm-action-confirm';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'false');
        overlay.dataset.action = action || '';
        overlay.style.position = 'absolute';
        overlay.style.visibility = 'hidden';
        overlay.style.pointerEvents = 'none';

        const titleEl = document.createElement('div');
        titleEl.className = 'vm-action-confirm__title';
        titleEl.textContent = copy.title;

        const messageEl = document.createElement('div');
        messageEl.className = 'vm-action-confirm__message';
        messageEl.textContent = copy.message;

        const actionsEl = document.createElement('div');
        actionsEl.className = 'vm-action-confirm__actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'vm-action-confirm__cancel';
        cancelBtn.textContent = 'Cancel';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'vm-action-confirm__confirm';
        confirmBtn.textContent = copy.confirmLabel;

        actionsEl.appendChild(cancelBtn);
        actionsEl.appendChild(confirmBtn);

        overlay.appendChild(titleEl);
        overlay.appendChild(messageEl);
        overlay.appendChild(actionsEl);

        document.body.appendChild(overlay);

        this.confirmationElement = overlay;
        this.activeConfirmButton = button;
        this.activeConfirmAction = action;

        button.classList.add('is-confirming');

        cancelBtn.addEventListener('click', () => {
            this.destroyActionConfirmation();
        });

        confirmBtn.addEventListener('click', () => {
            this.destroyActionConfirmation(true);
            this.executeVmAction(action);
        });

        this.boundConfirmOutsideHandler = (event) => {
            if (!this.confirmationElement) {
                return;
            }
            const target = event.target;
            if (!target) {
                return;
            }
            if (this.confirmationElement.contains(target)) {
                return;
            }
            if (this.activeConfirmButton && this.activeConfirmButton.contains(target)) {
                return;
            }
            this.destroyActionConfirmation();
        };

        this.boundConfirmKeyHandler = (event) => {
            if (!event) {
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                this.destroyActionConfirmation();
            }
        };

        this.boundConfirmRepositionHandler = () => {
            this.positionActionConfirmation();
        };

        document.addEventListener('mousedown', this.boundConfirmOutsideHandler, true);
        document.addEventListener('touchstart', this.boundConfirmOutsideHandler, true);
        document.addEventListener('keydown', this.boundConfirmKeyHandler, true);
        window.addEventListener('resize', this.boundConfirmRepositionHandler, true);
        window.addEventListener('scroll', this.boundConfirmRepositionHandler, true);

        this.positionActionConfirmation();

        requestAnimationFrame(() => {
            if (this.confirmationElement) {
                this.confirmationElement.classList.add('visible');
                confirmBtn.focus();
            }
        });
    }

    positionActionConfirmation() {
        if (!this.confirmationElement || !this.activeConfirmButton) {
            return;
        }

        const overlay = this.confirmationElement;

        overlay.classList.remove('vm-action-confirm--above');
        overlay.style.visibility = 'hidden';
        overlay.style.pointerEvents = 'none';

        requestAnimationFrame(() => {
            if (!this.confirmationElement || !this.activeConfirmButton) {
                return;
            }

            const currentOverlay = this.confirmationElement;
            const buttonRect = this.activeConfirmButton.getBoundingClientRect();
            const currentRect = currentOverlay.getBoundingClientRect();
            const viewportWidth = document.documentElement.clientWidth;
            const viewportHeight = window.innerHeight;
            const scrollY = window.scrollY || document.documentElement.scrollTop;
            const scrollX = window.scrollX || document.documentElement.scrollLeft;
            const edgeMargin = 20;

            let top = scrollY + buttonRect.bottom + 8;
            let alignAbove = false;

            if (top + currentRect.height > scrollY + viewportHeight - edgeMargin) {
                top = scrollY + buttonRect.top - currentRect.height - 8;
                alignAbove = true;
            }

            if (top < scrollY + edgeMargin) {
                top = scrollY + edgeMargin;
            }

            let left = scrollX + buttonRect.left + (buttonRect.width / 2) - (currentRect.width / 2);
            const minLeft = scrollX + edgeMargin;
            const maxLeft = scrollX + viewportWidth - currentRect.width - edgeMargin;
            if (left < minLeft) {
                left = minLeft;
            } else if (left > maxLeft) {
                left = Math.max(minLeft, maxLeft);
            }

            currentOverlay.style.top = `${Math.round(top)}px`;
            currentOverlay.style.left = `${Math.round(left)}px`;
            currentOverlay.style.visibility = 'visible';
            currentOverlay.style.pointerEvents = 'auto';
            currentOverlay.classList.toggle('vm-action-confirm--above', alignAbove);
        });
    }

    destroyActionConfirmation(immediate = false) {
        if (this.boundConfirmOutsideHandler) {
            document.removeEventListener('mousedown', this.boundConfirmOutsideHandler, true);
            document.removeEventListener('touchstart', this.boundConfirmOutsideHandler, true);
            this.boundConfirmOutsideHandler = null;
        }

        if (this.boundConfirmKeyHandler) {
            document.removeEventListener('keydown', this.boundConfirmKeyHandler, true);
            this.boundConfirmKeyHandler = null;
        }

        if (this.boundConfirmRepositionHandler) {
            window.removeEventListener('resize', this.boundConfirmRepositionHandler, true);
            window.removeEventListener('scroll', this.boundConfirmRepositionHandler, true);
            this.boundConfirmRepositionHandler = null;
        }

        if (this.activeConfirmButton) {
            this.activeConfirmButton.classList.remove('is-confirming');
        }

        if (this.confirmationElement) {
            const overlay = this.confirmationElement;
            const removeOverlay = () => {
                if (overlay && overlay.parentNode) {
                    overlay.parentNode.removeChild(overlay);
                }
            };

            if (!immediate) {
                overlay.classList.remove('visible');
                overlay.addEventListener('transitionend', removeOverlay, { once: true });
                setTimeout(removeOverlay, 200);
            } else {
                removeOverlay();
            }
        }

        this.confirmationElement = null;
        this.activeConfirmButton = null;
        this.activeConfirmAction = null;
    }

    buildVmActionButtons(vm) {
        const availability = this.getActionAvailability(vm && vm.state);
        const actions = [
            { action: 'edit', iconName: 'edit', tooltip: 'Edit VM', aria: 'Edit virtual machine' },
            { action: 'start', iconName: 'play_circle', tooltip: 'Start', aria: 'Start virtual machine' },
            { action: 'shutdown', iconName: 'power_settings_new', tooltip: 'Shut Down', aria: 'Shut down virtual machine' },
            { action: 'stop', iconName: 'stop_circle', tooltip: 'Turn Off', aria: 'Stop (Turn Off) virtual machine' },
            { action: 'reset', iconName: 'autorenew', tooltip: 'Reset', aria: 'Reset virtual machine' },
            { action: 'delete', iconName: 'delete', tooltip: 'Delete', aria: 'Delete virtual machine' },
        ];

        return actions.map(({ action, iconName, tooltip, aria }) => {
            const allowed = availability[action];
            const disabledAttr = allowed ? '' : 'disabled';
            const disabledClass = allowed ? '' : 'disabled';
            const iconMarkup = icon(iconName, { className: 'vm-action-symbol', size: 22 });

            return `
                    <button type="button" class="vm-action-btn ${disabledClass}" data-action="${action}"
                        data-tooltip="${tooltip}" aria-label="${aria}" ${disabledAttr}>
                        ${iconMarkup}
                    </button>
            `;
        }).join('');
    }

    getActionAvailability(state) {
        const normalized = typeof state === 'string' ? state.toLowerCase() : String(state || '').toLowerCase();
        const availability = {
            edit: true,  // Edit is always available
            start: false,
            shutdown: false,
            stop: false,
            reset: false,
            delete: false,
        };

        if (this.actionInProgress) {
            availability.edit = false;  // Disable edit during actions
            return availability;
        }

        if (normalized === 'running') {
            availability.shutdown = true;
            availability.stop = true;
            availability.reset = true;
        } else if (normalized === 'off') {
            availability.start = true;
            availability.delete = true;
        } else if (normalized === 'paused' || normalized === 'saved') {
            availability.start = true;
            availability.stop = true;
            availability.delete = true;
        } else if (normalized === 'deleting') {
            // Prevent any actions while deletion is pending
            Object.keys(availability).forEach(key => {
                availability[key] = false;
            });
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

    setActionFeedback(message, type = 'info', options = {}) {
        this.showActionToast(message, type, options);
    }

    ensureActionToast() {
        if (this.actionToastElement && document.body.contains(this.actionToastElement)) {
            return this.actionToastElement;
        }

        let toast = document.getElementById('vm-action-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'vm-action-toast';
            toast.className = 'connection-status-indicator vm-action-toast';
            toast.setAttribute('role', 'status');
            toast.setAttribute('aria-live', 'polite');
            toast.setAttribute('aria-atomic', 'true');
            toast.style.display = 'none';
            toast.innerHTML = `
                <div class="connection-status-content">
                    <div class="connection-status-icon" aria-hidden="true"></div>
                    <div class="connection-status-text">
                        <div class="connection-status-title"></div>
                        <div class="connection-status-message"></div>
                    </div>
                </div>
            `;
            document.body.appendChild(toast);
        }

        this.actionToastElement = toast;
        return toast;
    }

    hideActionToast(immediate = false) {
        const toast = this.actionToastElement || document.getElementById('vm-action-toast');
        if (!toast) {
            return;
        }

        if (this.toastHideTimer) {
            clearTimeout(this.toastHideTimer);
            this.toastHideTimer = null;
        }

        toast.classList.remove('visible');

        if (immediate) {
            toast.style.display = 'none';
            return;
        }

        setTimeout(() => {
            toast.style.display = 'none';
        }, 300);
    }

    getActionToastDefaults(type) {
        const defaults = {
            success: { icon: icon('check_circle', { size: 20 }), title: 'Action accepted' },
            error: { icon: icon('error', { size: 20 }), title: 'Action failed' },
            info: { icon: icon('pending', { size: 20 }), title: 'Working on it' },
        };

        return defaults[type] || defaults.info;
    }

    showActionToast(message, type = 'info', options = {}) {
        if (!message) {
            this.hideActionToast(true);
            return;
        }

        const toast = this.ensureActionToast();
        const iconEl = toast.querySelector('.connection-status-icon');
        const titleEl = toast.querySelector('.connection-status-title');
        const messageEl = toast.querySelector('.connection-status-message');

        const defaults = this.getActionToastDefaults(type);
        const title = options.title || defaults.title;
        const icon = options.icon || defaults.icon;

        toast.classList.remove('vm-action-toast--success', 'vm-action-toast--error', 'vm-action-toast--info');
        toast.classList.add(`vm-action-toast--${type}`);

        if (iconEl) {
            iconEl.innerHTML = icon;
        }
        if (titleEl) {
            titleEl.textContent = title;
        }
        if (messageEl) {
            messageEl.textContent = message;
        }

        toast.style.display = 'block';
        void toast.offsetWidth;
        toast.classList.add('visible');

        if (this.toastHideTimer) {
            clearTimeout(this.toastHideTimer);
            this.toastHideTimer = null;
        }

        const defaultDuration = type === 'error' ? 7000 : 4500;
        const duration = options.persist ? 0 : (options.duration || defaultDuration);

        if (duration > 0) {
            this.toastHideTimer = setTimeout(() => this.hideActionToast(), duration);
        }
    }

    getActionLabel(action) {
        const labels = {
            start: 'start',
            shutdown: 'shut down',
            stop: 'stop',
            reset: 'reset',
            delete: 'delete',
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

    enhanceShutdownError(errorMessage) {
        if (!errorMessage) {
            return errorMessage;
        }

        const message = String(errorMessage).toLowerCase();
        
        // Check if this looks like a graceful shutdown failure
        if (message.includes('stop-vm') || message.includes('shutdown')) {
            if (message.includes('unspecified') || 
                message.includes('failed') || 
                message.includes('timeout') ||
                message.includes('not respond')) {
                return `${errorMessage}\n\nNote: Graceful shutdown requires the guest OS to be responsive and have working Hyper-V Integration Services. If the VM is unresponsive, use "Turn Off" instead.`;
            }
        }

        return errorMessage;
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
            case 'delete':
                return `Delete command accepted for VM ${name}.`;
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
            case 'delete':
                return 'Deleting';
            default:
                return this.vmData && this.vmData.state ? this.vmData.state : 'Unknown';
        }
    }

    async executeVmAction(action) {
        if (!this.vmData || !this.vmData.name) {
            return;
        }

        this.destroyActionConfirmation(true);

        const host = this.vmHost || this.vmData.host || this.data.host;
        if (!host) {
            return;
        }

        if (action === 'delete') {
            await this.executeDeleteVm(host);
            return;
        }

        const actionLabel = this.getActionLabel(action);

        // Use RESTful endpoint with VM ID
        const endpoint = `/api/v1/resources/vms/${encodeURIComponent(this.vmData.id)}/${action}`;

        this.setButtonsBusy(true);
        this.setActionFeedback(`Sending ${actionLabel} request...`, 'info', {
            title: `${actionLabel.charAt(0).toUpperCase()}${actionLabel.slice(1)} in progress`,
            persist: true,
            icon: icon('hourglass_top', { size: 20 }),
        });

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
                this.setActionFeedback(message, 'success', {
                    title: 'VM action accepted',
                });

                const nextState = this.estimateNextState(action);
                if (this.vmData) {
                    this.vmData.state = nextState;
                }
                this.updateActionButtonStates();

                setTimeout(() => {
                    viewManager.switchView('vm', { 
                        id: this.vmData.id,
                        name: this.vmData.name, 
                        host 
                    }, { skipHistory: true });
                }, 400);
            } else {
                let detail = this.extractActionMessage(payload) || response.statusText || 'Request failed';
                
                // Enhance shutdown error messages with helpful guidance
                if (action === 'shutdown') {
                    detail = this.enhanceShutdownError(detail);
                }
                
                this.setActionFeedback(`Unable to ${actionLabel} VM: ${detail}`, 'error', {
                    title: 'VM action failed',
                });
            }
        } catch (error) {
            console.error('VM action error:', error);
            this.setActionFeedback(`Failed to ${actionLabel} VM: ${error.message}`, 'error', {
                title: 'VM action failed',
            });
        } finally {
            this.setButtonsBusy(false);
        }
    }

    async executeDeleteVm(host) {
        if (!host || !this.vmData || !this.vmData.name) {
            return;
        }

        this.setButtonsBusy(true);
        this.setActionFeedback(`Submitting delete request for ${this.vmData.name}...`, 'info', {
            title: 'Deleting virtual machine',
            persist: true,
            icon: icon('hourglass_top', { size: 20 }),
        });

        try {
            const response = await fetch(`/api/v1/resources/vms/${encodeURIComponent(this.vmData.id)}?delete_disks=true&force=false`, {
                method: 'DELETE',
                credentials: 'same-origin',
            });

            let payload = null;
            try {
                payload = await response.json();
            } catch (err) {
                payload = null;
            }

            if (response.ok) {
                const jobId = payload && payload.job_id ? payload.job_id : null;
                const message = jobId
                    ? `Delete job ${jobId} queued for VM ${this.vmData.name}.`
                    : `Delete request accepted for VM ${this.vmData.name}.`;
                this.setActionFeedback(message, 'success', {
                    title: 'VM deletion queued',
                });

                if (this.vmData) {
                    this.vmData.state = 'Deleting';
                }
                this.updateActionButtonStates();

                setTimeout(() => {
                    viewManager.switchView('vm', { 
                        id: this.vmData.id,
                        name: this.vmData.name, 
                        host 
                    }, { skipHistory: true });
                }, 400);
            } else {
                const detail = this.extractActionMessage(payload) || response.statusText || 'Request failed';
                this.setActionFeedback(`Unable to delete VM: ${detail}`, 'error', {
                    title: 'VM deletion failed',
                });
            }
        } catch (error) {
            console.error('VM delete action error:', error);
            this.setActionFeedback(`Failed to delete VM: ${error.message}`, 'error', {
                title: 'VM deletion failed',
            });
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

    buildMemoryHardwareItems(vm) {
        const items = [];
        const resolvedMemory = resolveVmMemoryValue(vm);
        const isDynamic = vm.dynamic_memory_enabled === true;

        items.push({
            label: 'Memory',
            value: this.formatMemory(resolvedMemory, isDynamic)
        });

        if (isDynamic) {
            if (typeof vm.memory_startup_gb !== 'undefined') {
                items.push({
                    label: 'Startup Memory',
                    value: this.formatMemory(vm.memory_startup_gb)
                });
            }
            if (typeof vm.memory_min_gb !== 'undefined') {
                items.push({
                    label: 'Minimum Memory',
                    value: this.formatMemory(vm.memory_min_gb)
                });
            }
            if (typeof vm.memory_max_gb !== 'undefined') {
                items.push({
                    label: 'Maximum Memory',
                    value: this.formatMemory(vm.memory_max_gb)
                });
            }
        }

        return items;
    }

    formatMemory(memoryGb, isDynamic = false) {
        const formatted = formatMemoryAmount(memoryGb);
        if (!formatted) {
            return '—';
        }

        if (isDynamic) {
            return `${formatted} (dynamic)`;
        }

        return formatted;
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

    buildHostOverviewValue(hostname) {
        const displayName = this.formatHostname(hostname);
        if (!hostname) {
            return { value: displayName, isHtml: false };
        }

        const safeHostname = escapeJsString(String(hostname));
        const safeDisplayName = this.escapeHtml(displayName);

        const hostHref = `/host/${encodeURIComponent(String(hostname))}`;
        return {
            value: `<a href="${hostHref}" class="vm-link" onclick="return viewManager.handleAnchorNavigation(event, 'host', { hostname: '${safeHostname}' });">${safeDisplayName}</a>`,
            isHtml: true
        };
    }

    getClusterStatus(vm, hostInfo) {
        const rawClustered = vm.clustered ?? vm.is_clustered ?? vm.vm_clustered;
        const hostCluster = hostInfo && hostInfo.cluster ? String(hostInfo.cluster).trim() : '';
        const clusterName = hostCluster || null;

        if (typeof rawClustered !== 'undefined' && rawClustered !== null) {
            if (typeof rawClustered === 'boolean') {
                if (rawClustered) {
                    return { label: 'Yes', clusterName, isClustered: true };
                }
                return { label: 'No', clusterName: null, isClustered: false };
            }

            const normalized = String(rawClustered).trim();
            if (normalized.length > 0) {
                const normalizedLower = normalized.toLowerCase();
                if (['yes', 'true', '1'].includes(normalizedLower)) {
                    return { label: 'Yes', clusterName, isClustered: true };
                }
                if (['no', 'false', '0'].includes(normalizedLower)) {
                    return { label: 'No', clusterName: null, isClustered: false };
                }
                return { label: this.formatValue(rawClustered, 'Unknown'), clusterName: null, isClustered: null };
            }
        }

        if (hostInfo && clusterName) {
            return { label: 'Yes', clusterName, isClustered: true };
        }
        if (hostInfo) {
            return { label: 'No', clusterName: null, isClustered: false };
        }
        return { label: 'Unknown', clusterName: null, isClustered: null };
    }

    buildClusterOverviewValue(vm, hostInfo) {
        const status = this.getClusterStatus(vm, hostInfo);
        if (status.isClustered && status.clusterName) {
            const safeStatus = this.escapeHtml(status.label);
            const safeClusterName = this.escapeHtml(status.clusterName);
            const clusterNameJs = escapeJsString(status.clusterName);
            const clusterHref = `/cluster/${encodeURIComponent(String(status.clusterName))}`;
            const clusterLink = `<a href="${clusterHref}" class="vm-link" onclick="return viewManager.handleAnchorNavigation(event, 'cluster', { name: '${clusterNameJs}' });">${safeClusterName}</a>`;
            return {
                value: `${safeStatus} (${clusterLink})`,
                isHtml: true
            };
        }

        const labelText = status.clusterName
            ? `${status.label} (${status.clusterName})`
            : status.label;
        return { value: labelText, isHtml: false };
    }

    findHost(inventory, hostname) {
        if (!inventory || !hostname) {
            return null;
        }
        const hosts = Array.isArray(inventory.hosts) ? inventory.hosts : [];
        return hosts.find(host => host && host.hostname === hostname) || null;
    }

    formatClusterState(vm, hostInfo) {
        const status = this.getClusterStatus(vm, hostInfo);
        if (status.clusterName) {
            return `${status.label} (${status.clusterName})`;
        }
        return status.label;
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

    async fetchVmById(vmId) {
        try {
            const response = await fetch(`/api/v1/vms/by-id/${encodeURIComponent(vmId)}`, { 
                credentials: 'same-origin' 
            });
            if (response.ok) {
                return await response.json();
            }
        } catch (error) {
            console.error('Error fetching VM by ID:', error);
        }
        return null;
    }

    setupResourceMenus() {
        this.resourceMenus = [];
        this.activeResourceMenu = null;
        this.boundResourceMenuClickHandler = null;
        this.boundResourceMenuOutsideHandler = null;
        this.boundResourceMenuRepositionHandler = null;

        const menuButtons = document.querySelectorAll('.resource-menu-btn');
        menuButtons.forEach(button => {
            button.addEventListener('click', (event) => this.handleResourceMenuClick(event));
        });
    }

    cleanupResourceMenus() {
        if (this.activeResourceMenu) {
            this.closeResourceMenu();
        }
        this.resourceMenus = [];
    }

    handleResourceMenuClick(event) {
        event.preventDefault();
        event.stopPropagation();

        const button = event.currentTarget;
        const resourceType = button.dataset.resourceType;
        const resourceId = button.dataset.resourceId;

        if (!resourceType || !resourceId) {
            return;
        }

        // Close any existing menu
        if (this.activeResourceMenu) {
            this.closeResourceMenu();
        }

        this.showResourceMenu(button, resourceType, resourceId);
    }

    showResourceMenu(button, resourceType, resourceId) {
        const menu = document.createElement('div');
        menu.className = 'resource-menu';
        menu.setAttribute('role', 'menu');
        
        const editLabel = resourceType === 'disk' ? 'Edit Disk' : 'Edit Network Adapter';
        const deleteLabel = resourceType === 'disk' ? 'Delete Disk' : 'Delete Network Adapter';
        
        menu.innerHTML = `
            <button type="button" class="resource-menu-item" data-action="edit" role="menuitem">
                ${icon('edit', { size: 18 })}
                <span>${editLabel}</span>
            </button>
            <button type="button" class="resource-menu-item resource-menu-item--danger" data-action="delete" role="menuitem">
                ${icon('delete', { size: 18 })}
                <span>${deleteLabel}</span>
            </button>
        `;

        document.body.appendChild(menu);
        this.activeResourceMenu = { menu, button, resourceType, resourceId };

        // Position the menu with viewport boundary detection
        menu.style.position = 'absolute';
        menu.style.visibility = 'hidden';
        menu.style.opacity = '0';

        // Add event listeners
        menu.querySelectorAll('.resource-menu-item').forEach(item => {
            item.addEventListener('click', (event) => {
                const action = event.currentTarget.dataset.action;
                this.handleResourceAction(action, resourceType, resourceId);
                this.closeResourceMenu();
            });
        });

        // Close menu when clicking outside
        this.boundResourceMenuOutsideHandler = (event) => {
            if (!this.activeResourceMenu) return;
            if (!menu.contains(event.target) && !button.contains(event.target)) {
                this.closeResourceMenu();
            }
        };
        
        setTimeout(() => {
            document.addEventListener('click', this.boundResourceMenuOutsideHandler, true);
        }, 0);

        // Reposition menu on scroll/resize
        this.boundResourceMenuRepositionHandler = () => {
            if (this.activeResourceMenu && this.activeResourceMenu.menu === menu) {
                this.positionResourceMenu(menu, button);
            }
        };
        
        window.addEventListener('scroll', this.boundResourceMenuRepositionHandler, true);
        window.addEventListener('resize', this.boundResourceMenuRepositionHandler, true);

        // Position and show menu after measuring
        requestAnimationFrame(() => {
            this.positionResourceMenu(menu, button);
            menu.style.visibility = 'visible';
            menu.style.opacity = '';
            menu.classList.add('visible');
        });
    }

    closeResourceMenu() {
        if (!this.activeResourceMenu) return;

        const { menu } = this.activeResourceMenu;
        menu.classList.remove('visible');
        
        if (this.boundResourceMenuOutsideHandler) {
            document.removeEventListener('click', this.boundResourceMenuOutsideHandler, true);
            this.boundResourceMenuOutsideHandler = null;
        }

        if (this.boundResourceMenuRepositionHandler) {
            window.removeEventListener('scroll', this.boundResourceMenuRepositionHandler, true);
            window.removeEventListener('resize', this.boundResourceMenuRepositionHandler, true);
            this.boundResourceMenuRepositionHandler = null;
        }

        setTimeout(() => {
            if (menu && menu.parentNode) {
                menu.parentNode.removeChild(menu);
            }
        }, 200);

        this.activeResourceMenu = null;
    }

    positionResourceMenu(menu, button) {
        const buttonRect = button.getBoundingClientRect();
        const menuRect = menu.getBoundingClientRect();
        const scrollY = window.scrollY || document.documentElement.scrollTop;
        const scrollX = window.scrollX || document.documentElement.scrollLeft;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const edgeMargin = 20;
        
        // Default positioning: below the button, aligned to the left
        let top = scrollY + buttonRect.bottom + 4;
        let left = scrollX + buttonRect.left;
        
        // Check if menu would extend past right edge of viewport
        if (left + menuRect.width > viewportWidth - edgeMargin) {
            // Align to the right edge of the button instead
            left = scrollX + buttonRect.right - menuRect.width;
        }
        
        // Ensure menu doesn't go past left edge
        if (left < edgeMargin) {
            left = edgeMargin;
        }
        
        // Check if menu would extend past bottom edge of viewport
        if (buttonRect.bottom + menuRect.height > viewportHeight - edgeMargin) {
            // Position above the button instead
            top = scrollY + buttonRect.top - menuRect.height - 4;
        }
        
        // Ensure menu doesn't go past top edge
        if (top < scrollY + edgeMargin) {
            top = scrollY + edgeMargin;
        }
        
        // Apply final position
        menu.style.top = `${Math.round(top)}px`;
        menu.style.left = `${Math.round(left)}px`;
    }

    handleResourceAction(action, resourceType, resourceId) {
        if (action === 'edit') {
            // Find the actual resource data to pass to the overlay
            let resourceData = null;
            if (resourceType === 'disk') {
                resourceData = this.vmData.disks.find(d => d.id === resourceId);
            } else if (resourceType === 'nic') {
                resourceData = this.vmData.networks.find(n => n.id === resourceId);
            }
            
            const overlayName = resourceType === 'disk' ? 'disk-edit' : 'nic-edit';
            overlayManager.open(overlayName, {
                vm_id: this.vmData.id,
                vm_name: this.vmData.name,
                host: this.vmData.host,
                resource_id: resourceId,
                resource_type: resourceType,
                resource_data: resourceData  // Pass actual resource data
            });
        } else if (action === 'delete') {
            this.confirmResourceDelete(resourceType, resourceId);
        }
    }

    confirmResourceDelete(resourceType, resourceId) {
        const resourceName = resourceType === 'disk' ? 'disk' : 'network adapter';
        const title = `Confirm ${resourceName} deletion`;
        const message = `Delete this ${resourceName}? This action cannot be undone.`;
        
        // Create confirmation dialog
        const overlay = document.createElement('div');
        overlay.className = 'resource-delete-confirm';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        
        overlay.innerHTML = `
            <div class="resource-delete-backdrop"></div>
            <div class="resource-delete-dialog">
                <div class="resource-delete-header">
                    <h3>${this.escapeHtml(title)}</h3>
                </div>
                <div class="resource-delete-body">
                    <p>${this.escapeHtml(message)}</p>
                </div>
                <div class="resource-delete-actions">
                    <button type="button" class="btn btn-secondary" data-action="cancel">Cancel</button>
                    <button type="button" class="btn btn-danger" data-action="confirm">Delete</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';
        
        const confirmBtn = overlay.querySelector('[data-action="confirm"]');
        const cancelBtn = overlay.querySelector('[data-action="cancel"]');
        const backdrop = overlay.querySelector('.resource-delete-backdrop');
        
        const close = () => {
            overlay.classList.remove('visible');
            document.body.style.overflow = '';
            setTimeout(() => {
                if (overlay.parentNode) {
                    overlay.parentNode.removeChild(overlay);
                }
            }, 200);
        };
        
        confirmBtn.addEventListener('click', async () => {
            close();
            await this.executeResourceDelete(resourceType, resourceId);
        });
        
        cancelBtn.addEventListener('click', close);
        backdrop.addEventListener('click', close);
        
        requestAnimationFrame(() => {
            overlay.classList.add('visible');
            confirmBtn.focus();
        });
    }

    async executeResourceDelete(resourceType, resourceId) {
        const resourceName = resourceType === 'disk' ? 'disk' : 'network adapter';
        const endpoint = resourceType === 'disk' 
            ? `/api/v1/resources/vms/${encodeURIComponent(this.vmData.id)}/disks/${encodeURIComponent(resourceId)}`
            : `/api/v1/resources/vms/${encodeURIComponent(this.vmData.id)}/nics/${encodeURIComponent(resourceId)}`;

        this.setActionFeedback(`Deleting ${resourceName}...`, 'info', {
            title: 'Deleting resource',
            persist: true,
            icon: icon('hourglass_top', { size: 20 }),
        });

        try {
            const response = await fetch(endpoint, {
                method: 'DELETE',
                credentials: 'same-origin',
            });

            let payload = null;
            try {
                payload = await response.json();
            } catch (err) {
                payload = null;
            }

            if (response.ok) {
                const message = payload && payload.message 
                    ? payload.message 
                    : `${resourceName.charAt(0).toUpperCase() + resourceName.slice(1)} deletion queued.`;
                this.setActionFeedback(message, 'success', {
                    title: 'Resource deletion queued',
                });

                // Refresh the view after a short delay
                setTimeout(() => {
                    viewManager.switchView('vm', { 
                        id: this.vmData.id,
                        name: this.vmData.name, 
                        host: this.vmData.host 
                    }, { skipHistory: true });
                }, 400);
            } else {
                const detail = (payload && payload.detail) || response.statusText || 'Request failed';
                const errorMsg = typeof detail === 'string' ? detail : (detail.message || JSON.stringify(detail));
                this.setActionFeedback(`Failed to delete ${resourceName}: ${errorMsg}`, 'error', {
                    title: 'Deletion failed',
                });
            }
        } catch (error) {
            console.error('Resource delete error:', error);
            this.setActionFeedback(`Failed to delete ${resourceName}: ${error.message}`, 'error', {
                title: 'Deletion failed',
            });
        }
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
                        <div class="empty-icon">${icon('check_circle', { className: 'status-success', size: 48 })}</div>
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
                    ${icon('warning', { className: 'host-icon status-warning', size: 28 })}
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
                        ${icon('autorenew', { className: 'action-icon', size: 24 })}
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
window.viewManager = viewManager;
