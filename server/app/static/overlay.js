// Overlay System - Reusable overlay panel component
class OverlayManager {
    constructor() {
        this.currentOverlay = null;
        this.overlays = new Map();
        this.overlayElement = null;
        this.isOpen = false;
    }

    init() {
        this.createOverlayDOM();
        this.registerDefaultOverlays();
    }

    createOverlayDOM() {
        // Create overlay container
        const overlay = document.createElement('div');
        overlay.id = 'overlay-container';
        overlay.className = 'overlay-container';
        overlay.innerHTML = `
            <div class="overlay-backdrop" id="overlay-backdrop"></div>
            <div class="overlay-panel">
                <div class="overlay-header">
                    <h2 class="overlay-title" id="overlay-title">Overlay</h2>
                    <button class="overlay-close" id="overlay-close" aria-label="Close overlay">
                        <span class="close-icon">×</span>
                    </button>
                </div>
                <div class="overlay-content" id="overlay-content">
                    <!-- Dynamic content goes here -->
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        this.overlayElement = overlay;

        // Setup event listeners
        document.getElementById('overlay-backdrop').addEventListener('click', () => this.close());
        document.getElementById('overlay-close').addEventListener('click', () => this.close());
        
        // ESC key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
    }

    registerOverlay(name, overlayClass) {
        this.overlays.set(name, overlayClass);
    }

    async open(overlayName, data = {}) {
        const OverlayClass = this.overlays.get(overlayName);
        if (!OverlayClass) {
            console.error('Overlay not found:', overlayName);
            return;
        }

        // Create and render overlay
        this.currentOverlay = new OverlayClass(data);
        const content = await this.currentOverlay.render();
        const title = this.currentOverlay.getTitle();

        // Update overlay DOM
        document.getElementById('overlay-title').textContent = title;
        document.getElementById('overlay-content').innerHTML = content;

        // Show overlay
        this.overlayElement.classList.add('open');
        this.isOpen = true;
        document.body.style.overflow = 'hidden'; // Prevent background scrolling

        // Initialize overlay
        if (typeof this.currentOverlay.init === 'function') {
            this.currentOverlay.init();
        }
    }

    close() {
        if (!this.isOpen) return;

        // Cleanup current overlay
        if (this.currentOverlay && typeof this.currentOverlay.cleanup === 'function') {
            this.currentOverlay.cleanup();
        }

        // Hide overlay
        this.overlayElement.classList.remove('open');
        this.isOpen = false;
        document.body.style.overflow = ''; // Restore scrolling

        this.currentOverlay = null;
    }

    registerDefaultOverlays() {
        this.registerOverlay('settings', SettingsOverlay);
        this.registerOverlay('provision-job', ProvisionJobOverlay);
        this.registerOverlay('job-details', JobDetailsOverlay);
        this.registerOverlay('notifications', NotificationsOverlay);
        this.registerOverlay('disk-create', DiskCreateOverlay);
        this.registerOverlay('disk-edit', DiskEditOverlay);
        this.registerOverlay('nic-create', NicCreateOverlay);
        this.registerOverlay('nic-edit', NicEditOverlay);
        this.registerOverlay('vm-edit', VMEditOverlay);
    }
}

// Base Overlay Class
class BaseOverlay {
    constructor(data = {}) {
        this.data = data;
    }

    getTitle() {
        return 'Overlay';
    }

    async render() {
        return '<div>Base Overlay - Override this method</div>';
    }

    init() {
        // Override to add event listeners, etc.
    }

    cleanup() {
        // Override to clean up
    }

    escapeHtml(value) {
        if (value === undefined || value === null) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}

// Settings Overlay
class SettingsOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.refreshDiagnosticsHandler = null;
        this.diagnosticsData = null;
        this.aboutSeeMoreHandler = null;
        this.aboutExpanded = false;
    }

    getTitle() {
        return 'Settings';
    }

    async render() {
        const [aboutData, diagnostics] = await Promise.all([
            this.fetchAboutInfo(),
            this.fetchDiagnostics(),
        ]);
        this.diagnosticsData = diagnostics;
        const build = aboutData?.build || {};
        const productName = this.escapeHtml(aboutData?.name || 'Aether-V');
        const description = this.escapeHtml(
            aboutData?.description || 'Hyper-V Virtual Machine Management Platform'
        );

        const details = [
            { label: 'Version', value: build.version },
            { label: 'Source', value: this.formatGitRef(build) },
            { label: 'Commit', value: this.formatCommit(build.git_commit) },
            { label: 'Repository State', value: build.git_state },
            { label: 'Source Control', value: build.source_control },
            { label: 'Built', value: this.formatBuildTime(build.build_time) },
            { label: 'Build Host', value: build.build_host },
        ].filter((item) => item.value);

        let summaryDetails = [];
        let moreDetails = [];

        if (details.length) {
            [summaryDetails, moreDetails] = [[details[0]], details.slice(1)];
        }

        const renderDetailItems = (items) => items
            .map((item) => `
                <div class="about-item">
                    <span class="about-label">${this.escapeHtml(item.label)}</span>
                    <span class="about-value">${this.escapeHtml(String(item.value))}</span>
                </div>
            `)
            .join('');

        let summaryMarkup = '';
        if (summaryDetails.length) {
            summaryMarkup = `
                <div class="about-grid about-grid--summary">
                    ${renderDetailItems(summaryDetails)}
                </div>
            `;
        } else {
            summaryMarkup = '<p class="empty">Build metadata unavailable.</p>';
        }

        const moreDetailsMarkup = moreDetails.length
            ? `
                <div class="about-grid about-grid--more" id="about-more-details" hidden aria-hidden="true">
                    ${renderDetailItems(moreDetails)}
                </div>
            `
            : '';

        const diagnosticsMarkup = this.renderDiagnosticsMarkup(diagnostics);
        const toggleTargets = [];
        if (moreDetails.length) {
            toggleTargets.push('about-more-details');
        }
        toggleTargets.push('diagnostics-section');
        const ariaControls = toggleTargets.join(' ');
        const seeMoreButtonMarkup = toggleTargets.length
            ? `
                <div class="about-actions">
                    <button
                        type="button"
                        class="see-more-btn"
                        id="about-see-more"
                        aria-expanded="false"
                        aria-controls="${this.escapeHtml(ariaControls)}"
                    >
                        See more
                    </button>
                </div>
            `
            : '';

        return `
            <div class="settings-section">
                <h3>Navigation Settings</h3>
                <div class="setting-item">
                    <div class="setting-header">
                        <div class="setting-info">
                            <div class="setting-title">Show hosts in navigation tree</div>
                            <div class="setting-description">When disabled, VMs will be shown as direct children of clusters</div>
                        </div>
                        <div class="setting-control">
                            <input type="checkbox" id="show-hosts" checked>
                        </div>
                    </div>
                </div>
            </div>

            <div class="settings-section">
                <h3>Display Settings</h3>
                <div class="setting-item">
                    <div class="setting-header">
                        <div class="setting-info">
                            <div class="setting-title">Theme</div>
                            <div class="setting-description">Choose your preferred color theme</div>
                        </div>
                        <div class="setting-control">
                            <select id="theme-mode" class="setting-select">
                                <option value="light">Light</option>
                                <option value="dark">Dark</option>
                                <option value="system">Match System</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="setting-item">
                    <div class="setting-header">
                        <div class="setting-info">
                            <div class="setting-title">Auto-refresh interval</div>
                            <div class="setting-description">Automatically refresh data at specified intervals</div>
                        </div>
                        <div class="setting-control">
                            <select id="refresh-interval" class="setting-select">
                                <option value="0">Disabled</option>
                                <option value="30" selected>30 seconds</option>
                                <option value="60">1 minute</option>
                                <option value="300">5 minutes</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>

            <div class="settings-section">
                <h3>About</h3>
                <div class="about-info">
                    <div class="about-brand">
                        <img
                            src="/assets/Logo.png"
                            alt="${productName} logo"
                            class="about-logo"
                            loading="lazy"
                        />
                        <div class="about-brand-text">
                            <p class="about-name">${productName}</p>
                            <p class="about-description">${description}</p>
                        </div>
                    </div>
                    ${summaryMarkup}
                    ${moreDetailsMarkup}
                    ${seeMoreButtonMarkup}
                </div>
            </div>

            <div class="settings-section diagnostics-section" id="diagnostics-section" hidden aria-hidden="true">
                <div class="settings-section-header">
                    <h3>Service Diagnostics</h3>
                    <button class="btn btn-tertiary" id="refresh-diagnostics" type="button">
                        Refresh
                    </button>
                </div>
                <div class="diagnostics-content" id="diagnostics-content">
                    ${diagnosticsMarkup}
                </div>
            </div>

            <div class="settings-actions">
                <button class="btn btn-secondary" onclick="overlayManager.close()">Cancel</button>
                <button class="btn" onclick="settingsOverlay.save()">Save Settings</button>
            </div>
        `;
    }

    init() {
        // Load saved settings
        const showHosts = localStorage.getItem('setting.showHosts') !== 'false';
        document.getElementById('show-hosts').checked = showHosts;

        const refreshInterval = localStorage.getItem('setting.refreshInterval') || '30';
        document.getElementById('refresh-interval').value = refreshInterval;

        const themeMode = localStorage.getItem('setting.themeMode') || 'system';
        document.getElementById('theme-mode').value = themeMode;

        const refreshButton = document.getElementById('refresh-diagnostics');
        if (refreshButton) {
            this.refreshDiagnosticsHandler = () => this.refreshDiagnostics();
            refreshButton.addEventListener('click', this.refreshDiagnosticsHandler);
        }

        const seeMoreBtn = document.getElementById('about-see-more');
        if (seeMoreBtn) {
            this.aboutSeeMoreHandler = () => {
                this.aboutExpanded = !this.aboutExpanded;
                this.updateAboutExpansion();
            };
            seeMoreBtn.addEventListener('click', this.aboutSeeMoreHandler);
        }

        this.aboutExpanded = false;
        this.updateAboutExpansion();
    }

    save() {
        const showHosts = document.getElementById('show-hosts').checked;
        const refreshInterval = document.getElementById('refresh-interval').value;
        const themeMode = document.getElementById('theme-mode').value;

        localStorage.setItem('setting.showHosts', showHosts);
        localStorage.setItem('setting.refreshInterval', refreshInterval);
        localStorage.setItem('setting.themeMode', themeMode);

        // Apply settings
        console.log('Settings saved:', { showHosts, refreshInterval, themeMode });
        
        // Apply theme immediately
        applyTheme(themeMode);
        
        // Close overlay
        overlayManager.close();

        // Immediately refresh the navigation tree to apply show hosts setting
        loadInventory();
    }

    cleanup() {
        if (this.refreshDiagnosticsHandler) {
            const refreshButton = document.getElementById('refresh-diagnostics');
            if (refreshButton) {
                refreshButton.removeEventListener('click', this.refreshDiagnosticsHandler);
            }
            this.refreshDiagnosticsHandler = null;
        }

        if (this.aboutSeeMoreHandler) {
            const seeMoreBtn = document.getElementById('about-see-more');
            if (seeMoreBtn) {
                seeMoreBtn.removeEventListener('click', this.aboutSeeMoreHandler);
            }
            this.aboutSeeMoreHandler = null;
        }
    }

    updateAboutExpansion() {
        const expanded = Boolean(this.aboutExpanded);
        const seeMoreBtn = document.getElementById('about-see-more');
        if (seeMoreBtn) {
            seeMoreBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            seeMoreBtn.textContent = expanded ? 'See less' : 'See more';
        }

        const extraDetails = document.getElementById('about-more-details');
        if (extraDetails) {
            extraDetails.classList.toggle('is-expanded', expanded);
            extraDetails.setAttribute('aria-hidden', expanded ? 'false' : 'true');
            extraDetails.toggleAttribute('hidden', !expanded);
        }

        const diagnosticsSection = document.getElementById('diagnostics-section');
        if (diagnosticsSection) {
            diagnosticsSection.classList.toggle('is-expanded', expanded);
            diagnosticsSection.setAttribute('aria-hidden', expanded ? 'false' : 'true');
            diagnosticsSection.toggleAttribute('hidden', !expanded);
        }
    }

    async fetchAboutInfo() {
        const fallbackBuild = window?.appConfig?.build;
        try {
            const response = await fetch('/api/v1/about', { credentials: 'same-origin' });
            if (response.ok) {
                return await response.json();
            }
        } catch (error) {
            console.error('Failed to load about information', error);
        }
        if (fallbackBuild) {
            return {
                name: window?.appConfig?.app_name || null,
                build: fallbackBuild,
            };
        }
        return null;
    }

    async fetchDiagnostics() {
        try {
            const response = await fetch('/api/v1/diagnostics/services', {
                credentials: 'same-origin',
            });
            if (response.ok) {
                return await response.json();
            }
            if (response.status === 403) {
                return {
                    errorMessage:
                        'Service diagnostics are unavailable because your account lacks the required permissions.',
                };
            }
            console.error(
                'Failed to load diagnostics information',
                response.status,
                response.statusText
            );
        } catch (error) {
            console.error('Failed to load diagnostics information', error);
        }
        return null;
    }

    formatBuildTime(value) {
        if (!value) return null;
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return parsed.toUTCString();
    }

    formatDuration(value) {
        const number = Number(value);
        if (!Number.isFinite(number) || number < 0) {
            return 'n/a';
        }
        if (number >= 3600) {
            const hours = number / 3600;
            return `${hours.toFixed(1)} hr`;
        }
        if (number >= 60) {
            const minutes = number / 60;
            return `${minutes.toFixed(1)} min`;
        }
        return `${number.toFixed(2)} s`;
    }

    formatBoolean(value) {
        return value ? 'Yes' : 'No';
    }

    formatPercent(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) {
            return 'n/a';
        }
        return `${number.toFixed(1)}%`;
    }

    formatCommit(commit) {
        if (!commit) return null;
        return commit.length > 12 ? `${commit.slice(0, 12)}…` : commit;
    }

    formatGitRef(build) {
        if (!build || !build.git_ref) {
            return null;
        }
        if (build.git_state && build.git_state !== 'branch') {
            return `${build.git_ref} (${build.git_state})`;
        }
        return build.git_ref;
    }

    formatTimestamp(value) {
        if (!value) {
            return 'n/a';
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return String(value);
        }
        return parsed.toLocaleString();
    }

    renderDiagnosticsMarkup(data) {
        if (!data) {
            return '<p class="empty">Diagnostics unavailable.</p>';
        }

        if (data.errorMessage) {
            return `<p class="empty">${this.escapeHtml(data.errorMessage)}</p>`;
        }

        const remote = data.remote_tasks || {};
        const fast = remote.fast_pool || {};
        const jobPool = remote.job_pool || {};
        const jobs = data.jobs || {};
        const inventory = data.inventory || {};
        const hostDeployment = data.host_deployment || {};
        const cpuPercent = this.formatPercent(remote.cpu_percent);
        const memoryPercent = this.formatPercent(remote.memory_percent);
        const maxedOutFor = this.formatDuration(remote.maxed_out_for_seconds);
        const currentMaxWorkers = remote.current_max_workers ?? fast.max_workers ?? 'n/a';
        const configuredFastLimit = remote.configured_max_workers ?? 'n/a';
        const dynamicCeiling = remote.dynamic_ceiling ?? 'n/a';
        const fastWorkerDisplay =
            `${this.escapeHtml(String(fast.current_workers ?? 'n/a'))} / ` +
            `${this.escapeHtml(String(currentMaxWorkers))}`;
        const fastLimitDisplay =
            `${this.escapeHtml(String(configuredFastLimit))} / ` +
            `${this.escapeHtml(String(dynamicCeiling))}`;

        return `
            <div class="diagnostics-grid">
                <div class="diagnostic-card">
                    <div class="diagnostic-title">Remote Task Pools</div>
                    <div class="diagnostic-metrics">
                        <div class="diagnostic-metric">
                            <span class="metric-label">Fast queue depth</span>
                            <span class="metric-value">${this.escapeHtml(String(fast.queue_depth ?? 'n/a'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Fast workers</span>
                            <span class="metric-value">${fastWorkerDisplay}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Configured fast limit</span>
                            <span class="metric-value">${fastLimitDisplay}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">CPU utilisation</span>
                            <span class="metric-value">${this.escapeHtml(cpuPercent)}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Memory utilisation</span>
                            <span class="metric-value">${this.escapeHtml(memoryPercent)}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">At capacity</span>
                            <span class="metric-value">${this.escapeHtml(maxedOutFor)}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Job queue depth</span>
                            <span class="metric-value">${this.escapeHtml(String(jobPool.queue_depth ?? 'n/a'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Job workers</span>
                            <span class="metric-value">${this.escapeHtml(String(jobPool.current_workers ?? 'n/a'))} / ${this.escapeHtml(String(jobPool.configured_workers ?? 'n/a'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Average duration</span>
                            <span class="metric-value">${this.escapeHtml(this.formatDuration(remote.average_duration_seconds))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Dynamic adjustments</span>
                            <span class="metric-value">${this.escapeHtml(String(remote.dynamic_adjustments ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Completed tasks</span>
                            <span class="metric-value">${this.escapeHtml(String(remote.completed_tasks ?? '0'))}</span>
                        </div>
                    </div>
                </div>
                <div class="diagnostic-card">
                    <div class="diagnostic-title">Job Service</div>
                    <div class="diagnostic-metrics">
                        <div class="diagnostic-metric">
                            <span class="metric-label">Queue depth</span>
                            <span class="metric-value">${this.escapeHtml(String(jobs.queue_depth ?? 'n/a'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Workers</span>
                            <span class="metric-value">${this.escapeHtml(String(jobs.worker_count ?? 'n/a'))} / ${this.escapeHtml(String(jobs.configured_concurrency ?? 'n/a'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Running jobs</span>
                            <span class="metric-value">${this.escapeHtml(String(jobs.running_jobs ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Pending jobs</span>
                            <span class="metric-value">${this.escapeHtml(String(jobs.pending_jobs ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Failed jobs</span>
                            <span class="metric-value">${this.escapeHtml(String(jobs.failed_jobs ?? '0'))}</span>
                        </div>
                    </div>
                </div>
                <div class="diagnostic-card">
                    <div class="diagnostic-title">Inventory Service</div>
                    <div class="diagnostic-metrics">
                        <div class="diagnostic-metric">
                            <span class="metric-label">Last refresh</span>
                            <span class="metric-value">${this.escapeHtml(this.formatTimestamp(inventory.last_refresh))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Hosts tracked</span>
                            <span class="metric-value">${this.escapeHtml(String(inventory.hosts_tracked ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">VMs tracked</span>
                            <span class="metric-value">${this.escapeHtml(String(inventory.vms_tracked ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Refresh in progress</span>
                            <span class="metric-value">${this.escapeHtml(this.formatBoolean(inventory.refresh_in_progress ?? false))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Initial sync</span>
                            <span class="metric-value">${this.escapeHtml(this.formatBoolean(inventory.initial_refresh_succeeded ?? false))}</span>
                        </div>
                    </div>
                </div>
                <div class="diagnostic-card">
                    <div class="diagnostic-title">Host Deployment</div>
                    <div class="diagnostic-metrics">
                        <div class="diagnostic-metric">
                            <span class="metric-label">Enabled</span>
                            <span class="metric-value">${this.escapeHtml(this.formatBoolean(hostDeployment.enabled ?? false))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Ingress ready</span>
                            <span class="metric-value">${this.escapeHtml(this.formatBoolean(hostDeployment.ingress_ready ?? false))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Startup status</span>
                            <span class="metric-value">${this.escapeHtml(String(hostDeployment.startup?.status ?? 'unknown'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Hosts completed</span>
                            <span class="metric-value">${this.escapeHtml(String(hostDeployment.startup?.completed_hosts ?? '0'))} / ${this.escapeHtml(String(hostDeployment.startup?.total_hosts ?? '0'))}</span>
                        </div>
                        <div class="diagnostic-metric">
                            <span class="metric-label">Failures</span>
                            <span class="metric-value">${this.escapeHtml(String(hostDeployment.startup?.failed_hosts ?? '0'))}</span>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    async refreshDiagnostics() {
        const refreshButton = document.getElementById('refresh-diagnostics');
        const container = document.getElementById('diagnostics-content');
        if (refreshButton) {
            refreshButton.disabled = true;
            refreshButton.textContent = 'Refreshing…';
        }
        if (container) {
            container.innerHTML = '<div class="diagnostics-loading">Loading diagnostics…</div>';
        }

        try {
            const diagnostics = await this.fetchDiagnostics();
            this.diagnosticsData = diagnostics;
            if (container) {
                container.innerHTML = this.renderDiagnosticsMarkup(diagnostics);
            }
        } finally {
            if (refreshButton) {
                refreshButton.disabled = false;
                refreshButton.textContent = 'Refresh';
            }
        }
    }
}

// ProvisionJobOverlay - Pydantic-based implementation (Phase 7)
// Delegates to ProvisionFormPydantic for all form rendering and logic
class ProvisionJobOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.pydanticForm = null;
    }

    getTitle() {
        return 'Create Virtual Machine';
    }

    async render() {
        return `
            <div class="schema-form" id="provision-job-root">
                <div class="form-loading">Loading form...</div>
            </div>
        `;
    }

    async init() {
        // Use the new Pydantic-based form
        if (typeof window.ProvisionFormPydantic === 'function') {
            this.pydanticForm = new window.ProvisionFormPydantic(this.data);
            await this.pydanticForm.init();
        } else {
            console.error('ProvisionFormPydantic not loaded');
            const rootEl = document.getElementById('provision-job-root');
            if (rootEl) {
                rootEl.innerHTML = '<div class="form-error">Form component not loaded. Please refresh the page.</div>';
            }
        }
    }

    cleanup() {
        if (this.pydanticForm && typeof this.pydanticForm.cleanup === 'function') {
            this.pydanticForm.cleanup();
        }
    }
}

// Legacy schema-based overlay (deprecated but kept for reference)
// This is the OLD implementation that will be removed after Phase 7 is complete
class ProvisionJobOverlayLegacy extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.schema = this.resolveInitialSchema();
        this.hosts = [];
        this.rootEl = null;
        this.formEl = null;
        this.messagesEl = null;
        this.stateListener = null;
    }

    resolveInitialSchema() {
        const sources = [
            () => this.data?.schema,
            () => window?.jobSchema,
            () => window?.appConfig?.job_schema,
        ];

        for (const getter of sources) {
            try {
                const value = getter();
                if (value) {
                    return value;
                }
            } catch (error) {
                // Ignore lookup errors from optional chaining fallbacks
            }
        }

        return null;
    }

    getTitle() {
        return 'Create Virtual Machine (Legacy)';
    }

    async render() {
        return `
            <div class="schema-form" id="provision-job-root">
                <div class="form-loading">Loading schema...</div>
            </div>
        `;
    }

    init() {
        this.rootEl = document.getElementById('provision-job-root');
        if (!this.rootEl) {
            console.error('Provision job root element missing');
            return;
        }

        this.rootEl.innerHTML = `
            <div class="form-loading">Loading schema...</div>
        `;

        this.stateListener = (event) => this.applyAvailability(event.detail);
        document.addEventListener('agentDeploymentStateChanged', this.stateListener);

        this.prepareForm();
        this.applyAvailability(window.agentDeploymentState);
    }

    async prepareForm() {
        try {
            const [schema, hosts] = await Promise.all([
                this.schema ? Promise.resolve(this.schema) : this.fetchSchema(),
                this.fetchHosts(),
            ]);

            this.schema = schema;
            window.jobSchema = this.schema;
            this.hosts = hosts;
            this.renderForm();
        } catch (error) {
            console.error('Failed to prepare provisioning form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load provisioning form data. Please try again later.</div>
            `;
        }
    }

    async fetchSchema() {
        // Fetch all three component schemas and compose them into a single form
        // vm-create: VM hardware + guest configuration (local admin, domain join, ansible)
        // disk-create: Disk configuration
        // nic-create: Network adapter hardware + guest IP configuration
        const [vmSchema, diskSchema, nicSchema] = await Promise.all([
            fetch('/api/v1/schema/vm-create', { credentials: 'same-origin' }).then(r => r.json()),
            fetch('/api/v1/schema/disk-create', { credentials: 'same-origin' }).then(r => r.json()),
            fetch('/api/v1/schema/nic-create', { credentials: 'same-origin' }).then(r => r.json()),
        ]);

        // Compose a single schema from the three component schemas
        const composedSchema = {
            id: 'managed-deployment',
            name: 'Virtual Machine Deployment',
            description: 'Create a complete virtual machine with disk, network adapter, and guest configuration',
            version: vmSchema.version || 1,
            fields: [],
            parameter_sets: []
        };

        // Add all VM fields (hardware + guest config)
        vmSchema.fields.forEach(field => {
            composedSchema.fields.push(field);
        });

        // Add disk fields (excluding vm_id)
        diskSchema.fields.forEach(field => {
            if (field.id !== 'vm_id') {
                // Add disk fields, avoiding duplicates with VM schema
                if (field.id === 'disk_size_gb') {
                    composedSchema.fields.push(field);
                } else if (field.id === 'storage_class' && !composedSchema.fields.find(f => f.id === 'storage_class')) {
                    // Only add storage_class if not already present from VM schema
                    composedSchema.fields.push(field);
                } else if (!composedSchema.fields.find(f => f.id === field.id)) {
                    composedSchema.fields.push(field);
                }
            }
        });

        // Add network fields including guest IP configuration (excluding vm_id)
        nicSchema.fields.forEach(field => {
            if (field.id !== 'vm_id' && field.id !== 'adapter_name') {
                // Skip adapter_name as the primary adapter doesn't need naming
                // Include both hardware (network) and guest config (IP settings) fields
                composedSchema.fields.push(field);
            }
        });

        // Combine parameter sets from all schemas
        if (vmSchema.parameter_sets) {
            composedSchema.parameter_sets.push(...vmSchema.parameter_sets);
        }
        if (diskSchema.parameter_sets) {
            composedSchema.parameter_sets.push(...diskSchema.parameter_sets);
        }
        if (nicSchema.parameter_sets) {
            composedSchema.parameter_sets.push(...nicSchema.parameter_sets);
        }

        return composedSchema;
    }

    async fetchHosts() {
        const response = await fetch('/api/v1/hosts', { credentials: 'same-origin' });
        if (!response.ok) {
            throw new Error(`Host list request failed: ${response.status}`);
        }

        const hosts = await response.json();
        return Array.isArray(hosts) ? hosts.filter((host) => host.connected) : [];
    }

    renderForm() {
        if (!this.schema) {
            return;
        }

        const fieldSetMap = this.buildParameterSetMap();
        const vmField = this.schema.fields.find((field) => field.id === 'vm_name') || null;
        const fieldsHtml = this.schema.fields
            .filter((field) => field.id !== 'vm_name')
            .map((field) => this.renderField(field, fieldSetMap.get(field.id) || []))
            .join('');

        const parameterSetHtml = this.renderParameterSets();
        const primaryControls = this.renderPrimaryControls(vmField);

        this.rootEl.innerHTML = `
            <form id="provision-job-form" class="schema-form-body">
                <div id="provision-job-messages" class="form-messages" role="alert"></div>
                ${primaryControls}
                <div class="schema-fields">${fieldsHtml}</div>
                ${parameterSetHtml}
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="provision-job-cancel">Cancel</button>
                    <button type="submit" class="btn" id="provision-job-submit">Submit Job</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('provision-job-form');
        this.messagesEl = document.getElementById('provision-job-messages');
        const cancelBtn = document.getElementById('provision-job-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));

        this.applyAvailability(window.agentDeploymentState);
    }

    buildParameterSetMap() {
        const map = new Map();
        const sets = this.schema?.parameter_sets || [];
        sets.forEach((set) => {
            (set.members || []).forEach((member) => {
                const existing = map.get(member) || [];
                existing.push(set);
                map.set(member, existing);
            });
        });
        return map;
    }

    renderField(field, parameterSets) {
        const fieldId = `schema-${field.id}`;
        const requiredPill = this.renderRequiredPill(field.required);
        const labelText = this.escapeHtml(field.label || field.id);
        const description = field.description ? `<p class="field-description">${this.escapeHtml(field.description)}</p>` : '';
        const tags = this.renderFieldTags(field, parameterSets);
        const inputControl = this.renderInputControl(field, fieldId);

        return `
            <div class="schema-field" data-field-id="${field.id}">
                <div class="field-header">
                    <div class="field-title">
                        <label for="${fieldId}" class="field-label">${labelText}</label>
                        ${requiredPill}
                    </div>
                    ${tags}
                </div>
                <div class="field-control">${inputControl}</div>
                ${description}
            </div>
        `;
    }

    renderFieldTags(field, parameterSets) {
        const tags = [];
        if (parameterSets.length > 0) {
            parameterSets.forEach((set) => {
                const label = this.escapeHtml(set.label || set.id);
                tags.push(`<span class="field-tag">${label}</span>`);
            });
        }

        const applicability = field.applicability;
        if (applicability?.os_family) {
            const families = applicability.os_family.map((fam) => fam.charAt(0).toUpperCase() + fam.slice(1));
            tags.push(`<span class="field-tag field-tag-muted">${this.escapeHtml(families.join(', '))} only</span>`);
        }

        if (!tags.length) {
            return '';
        }

        return `<div class="field-tags">${tags.join('')}</div>`;
    }

    renderRequiredPill(isRequired) {
        return isRequired ? '<span class="field-required-pill">Required</span>' : '';
    }

    renderPrimaryControls(vmField) {
        const hostControl = this.renderHostSelector();
        const vmControl = vmField ? this.renderVmNameField(vmField) : '';

        return `
            <section class="primary-controls">
                ${hostControl}
                ${vmControl}
            </section>
        `;
    }

    renderHostSelector() {
        const requiredPill = this.renderRequiredPill(true);
        if (!this.hosts.length) {
            return `
                <div class="primary-field" data-primary="host">
                    <div class="field-header">
                        <div class="field-title">
                            <label for="schema-target_host" class="field-label">Destination host</label>
                            ${requiredPill}
                        </div>
                    </div>
                    <div class="field-control">
                        <select id="schema-target_host" name="target_host" class="primary-select" disabled>
                            <option value="">No connected hosts available</option>
                        </select>
                    </div>
                    <p class="field-description field-note">Reconnect a host to enable provisioning.</p>
                </div>
            `;
        }

        const options = this.hosts
            .map((host) => {
                const hostname = this.escapeHtml(host.hostname || '');
                const cluster = host.cluster ? ` (${this.escapeHtml(host.cluster)})` : '';
                return `<option value="${hostname}">${hostname}${cluster}</option>`;
            })
            .join('');

        return `
            <div class="primary-field" data-primary="host">
                <div class="field-header">
                    <div class="field-title">
                        <label for="schema-target_host" class="field-label">Destination host</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">
                    <select id="schema-target_host" name="target_host" class="primary-select" required>
                        <option value="">Select a connected host</option>
                        ${options}
                    </select>
                </div>
                <p class="field-description field-note">Only hosts that are currently connected appear in this list.</p>
            </div>
        `;
    }

    renderVmNameField(vmField) {
        const fieldId = 'schema-vm_name';
        const requiredPill = this.renderRequiredPill(vmField.required);
        const labelText = this.escapeHtml(vmField.label || vmField.id);
        const description = vmField.description
            ? `<p class="field-description">${this.escapeHtml(vmField.description)}</p>`
            : '';
        const note = '<p class="field-description field-note">This value becomes both the VM name and the guest hostname.</p>';
        const inputControl = this.renderInputControl(vmField, fieldId);

        return `
            <div class="primary-field" data-primary="vm-name">
                <div class="field-header">
                    <div class="field-title">
                        <label for="${fieldId}" class="field-label">${labelText}</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">${inputControl}</div>
                ${description}
                ${note}
            </div>
        `;
    }

    escapeHtml(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    renderInputControl(field, fieldId) {
        const type = (field.type || 'string').toLowerCase();
        const defaultValue = field.default ?? '';
        const validations = field.validations || {};
        const requiredAttr = field.required ? 'required' : '';
        const placeholder = field.hint ? `placeholder="${this.escapeHtml(field.hint)}"` : '';

        if (type === 'boolean') {
            const checked = defaultValue === true ? 'checked' : '';
            return `
                <label class="checkbox-field">
                    <input type="checkbox" id="${fieldId}" name="${field.id}" ${checked} />
                    <span>Enable</span>
                </label>
            `;
        }

        if (type === 'integer') {
            const min = validations.minimum !== undefined ? `min="${validations.minimum}"` : '';
            const max = validations.maximum !== undefined ? `max="${validations.maximum}"` : '';
            const valueAttr = defaultValue !== '' ? `value="${this.escapeHtml(defaultValue)}"` : '';
            return `<input type="number" inputmode="numeric" step="1" id="${fieldId}" name="${field.id}" ${min} ${max} ${placeholder} ${valueAttr} ${requiredAttr} />`;
        }

        if (type === 'multiline') {
            return `<textarea id="${fieldId}" name="${field.id}" rows="4" ${placeholder} ${requiredAttr}>${this.escapeHtml(defaultValue)}</textarea>`;
        }

        const inputType = type === 'secret' ? 'password' : 'text';
        const patternValue = validations.pattern ? this.escapeHtml(validations.pattern) : '';
        const pattern = patternValue ? `pattern="${patternValue}"` : '';
        const valueAttr = defaultValue !== '' ? `value="${this.escapeHtml(defaultValue)}"` : '';
        return `<input type="${inputType}" id="${fieldId}" name="${field.id}" ${pattern} ${placeholder} ${valueAttr} ${requiredAttr} />`;
    }

    renderParameterSets() {
        const parameterSets = this.schema?.parameter_sets || [];
        if (!parameterSets.length) {
            return '';
        }

        const rows = parameterSets
            .map((set) => {
                const title = this.escapeHtml(set.label || set.id || 'parameter set');
                const mode = this.escapeHtml(set.mode || 'unspecified');
                const descriptionText = this.escapeHtml(set.description || '');
                const description = descriptionText
                    ? `<div class="parameter-set-description">${descriptionText}</div>`
                    : '';
                const members = this.renderParameterSetMembers(set);

                return `
                    <div class="parameter-set">
                        <div class="parameter-set-title">${title}</div>
                        <div class="parameter-set-mode">Mode: ${mode}</div>
                        ${description}
                        ${members}
                    </div>
                `;
            })
            .join('');

        return `
            <div class="parameter-set-summary">
                <h3>Parameter Sets</h3>
                ${rows}
            </div>
        `;
    }

    renderParameterSetMembers(set) {
        const members = Array.isArray(set.members) ? set.members : null;
        if (members && members.length) {
            return `<div class="parameter-set-members">Fields: ${this.escapeHtml(members.join(', '))}</div>`;
        }

        const variants = Array.isArray(set.variants) ? set.variants : null;
        if (variants && variants.length) {
            const variantRows = variants
                .map((variant) => {
                    const variantLabel = this.escapeHtml(variant.label || variant.id || 'Variant');
                    const requiredFields = Array.isArray(variant.required) ? variant.required : [];
                    const optionalFields = Array.isArray(variant.optional) ? variant.optional : [];

                    const requiredHtml = requiredFields.length
                        ? `<div class="parameter-set-variant-detail"><span class="parameter-set-variant-label">Required:</span> ${this.escapeHtml(requiredFields.join(', '))}</div>`
                        : '';
                    const optionalHtml = optionalFields.length
                        ? `<div class="parameter-set-variant-detail"><span class="parameter-set-variant-label">Optional:</span> ${this.escapeHtml(optionalFields.join(', '))}</div>`
                        : '';

                    return `
                        <div class="parameter-set-variant">
                            <div class="parameter-set-variant-title">${variantLabel}</div>
                            ${requiredHtml}
                            ${optionalHtml}
                        </div>
                    `;
                })
                .join('');

            return `
                <div class="parameter-set-variants">
                    <div class="parameter-set-variants-heading">Variants:</div>
                    ${variantRows}
                </div>
            `;
        }

        return '<div class="parameter-set-members">Fields: none specified</div>';
    }

    async handleSubmit(event) {
        event.preventDefault();
        if (!this.formEl || !this.schema) {
            return;
        }

        const submitBtn = document.getElementById('provision-job-submit');
        submitBtn?.setAttribute('disabled', 'disabled');
        this.showMessage('', '');

        const deploymentState = window.agentDeploymentState;
        if (deploymentState && !deploymentState.provisioning_available) {
            this.applyAvailability(deploymentState);
            return;
        }

        if (!this.hosts.length) {
            this.showMessage('No connected hosts are available for provisioning.', 'error');
            submitBtn?.removeAttribute('disabled');
            return;
        }

        if (typeof this.formEl.reportValidity === 'function' && !this.formEl.reportValidity()) {
            submitBtn?.removeAttribute('disabled');
            return;
        }

        const targetHostControl = this.formEl.elements['target_host'];
        const targetHost = targetHostControl ? targetHostControl.value.trim() : '';
        if (!targetHost) {
            this.showMessage('Select a destination host before submitting.', 'error');
            submitBtn?.removeAttribute('disabled');
            return;
        }

        const payload = this.collectValues();

        try {
            const response = await fetch('/api/v1/managed-deployments', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    schema_version: this.schema.version,
                    target_host: targetHost,
                    values: payload
                })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                if (error?.agent_deployment) {
                    updateAgentDeploymentState(error.agent_deployment);
                }
                const errorMessages = this.extractErrorMessages(error);
                this.showMessage(errorMessages.join('<br>') || 'Failed to submit job.', 'error');
                this.applyAvailability(window.agentDeploymentState);
                return;
            }

            const job = await response.json();
            overlayManager.close();
            if (typeof showNotificationToast === 'function') {
                showNotificationToast({
                    title: 'Job queued',
                    message: `Job ${job.job_id} queued successfully.`,
                });
            }
            loadNotifications().catch((refreshError) => {
                console.error('Failed to refresh notifications after job submission:', refreshError);
            });
        } catch (error) {
            console.error('Failed to submit provisioning job:', error);
            this.showMessage('Unexpected error submitting job.', 'error');
            this.applyAvailability(window.agentDeploymentState);
        } finally {
            if (window.agentDeploymentState?.provisioning_available !== false) {
                submitBtn?.removeAttribute('disabled');
            }
        }
    }

    collectValues() {
        const values = {};
        this.schema.fields.forEach((field) => {
            const control = this.formEl.elements[field.id];
            if (!control) {
                values[field.id] = null;
                return;
            }

            const type = (field.type || 'string').toLowerCase();
            if (type === 'boolean') {
                values[field.id] = control.checked;
                return;
            }

            const rawValue = control.value;
            if (rawValue === '') {
                values[field.id] = null;
                return;
            }

            if (type === 'integer') {
                values[field.id] = Number.parseInt(rawValue, 10);
            } else {
                values[field.id] = rawValue;
            }
        });

        return values;
    }

    extractErrorMessages(errorPayload) {
        if (!errorPayload) {
            return [];
        }
        if (Array.isArray(errorPayload?.detail)) {
            return errorPayload.detail.map((item) => item.msg || JSON.stringify(item));
        }
        if (typeof errorPayload.detail === 'string') {
            return [errorPayload.detail];
        }
        if (Array.isArray(errorPayload.errors)) {
            return errorPayload.errors;
        }
        if (Array.isArray(errorPayload?.detail?.errors)) {
            return errorPayload.detail.errors;
        }
        if (errorPayload.detail?.message) {
            return [errorPayload.detail.message];
        }
        return [];
    }

    showMessage(message, level) {
        if (!this.messagesEl) {
            return;
        }

        this.messagesEl.classList.remove('error', 'success', 'info');
        if (!message) {
            this.messagesEl.innerHTML = '';
            return;
        }

        if (level === 'error') {
            this.messagesEl.classList.add('error');
        }
        if (level === 'success') {
            this.messagesEl.classList.add('success');
        }
        if (level === 'info') {
            this.messagesEl.classList.add('info');
        }

        this.messagesEl.innerHTML = message;
    }

    applyAvailability(state) {
        if (typeof window.applyProvisioningAvailability === 'function') {
            window.applyProvisioningAvailability(state || window.agentDeploymentState);
        }
    }

    cleanup() {
        if (this.stateListener) {
            document.removeEventListener('agentDeploymentStateChanged', this.stateListener);
            this.stateListener = null;
        }
    }
}

// Job Details Overlay
class JobDetailsOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.job = data.job || null;
        this.jobId = data.jobId || (this.job ? this.job.job_id : null);
        this.autoSubscribe = data.autoSubscribe !== false;
        this.followOutput = true;
        this.logLines = Array.isArray(this.job?.output) ? [...this.job.output] : [];
        this.durationTimer = null;
        this.jobSubscription = null;
        this.rootEl = null;
        this.statusBadgeEl = null;
        this.statusTextEl = null;
        this.jobTypeEl = null;
        this.jobIdEl = null;
        this.createdEl = null;
        this.startedEl = null;
        this.completedEl = null;
        this.durationEl = null;
        this.vmNameEl = null;
        this.targetHostEl = null;
        this.imageEl = null;
        this.detailsToggleEl = null;
        this.detailsExpandedEl = null;
        this.autoScrollInput = null;
        this.copyButtonEl = null;
        this.logContainerEl = null;
        this.logCodeEl = null;
        this.childJobsContainer = null;
    }

    getTitle() {
        return 'Job Details';
    }

    getJobSummaryTitle(job = this.job) {
        if (!job) {
            return 'Job Details';
        }
        const label = this.formatJobType(job.job_type);
        const target = this.extractVmName(job) || job.job_id || 'Job';
        return `${label} • ${target}`;
    }

    async render() {
        const job = this.job || {};
        const statusLabel = this.formatStatus(job.status);
        const statusClass = job.status ? `status-${job.status}` : 'status-pending';
        const jobId = job.job_id || this.jobId || 'Unknown';
        const jobTypeLabel = this.formatJobType(job.job_type);
        const created = this.formatTimestamp(job.created_at);
        const started = this.formatTimestamp(job.started_at);
        const completed = this.formatCompletion(job);
        const duration = this.computeDuration(job);
        const vmName = this.extractVmName(job) || '—';
        const targetHost = job.target_host || '—';
        const imageName = this.extractField(job, ['image_name', 'image']) || '—';
        const logText = this.logLines.length ? this.logLines.join('\n') : 'Waiting for output...';
        const details = job.parameters ? JSON.stringify(job.parameters, null, 2) : '{}';
        const jobSummaryTitle = this.getJobSummaryTitle(job);
        const childJobsSection = this.renderChildJobSection(job.child_jobs);

        return `
            <div class='job-details' data-job-id='${this.escapeHtml(jobId)}'>
                <div class='job-header'>
                    <div class='job-header-text'>
                        <div class='job-title'>${this.escapeHtml(jobSummaryTitle)}</div>
                        <div class='job-id'>Job ID: <span data-field='job-id'>${this.escapeHtml(jobId)}</span></div>
                    </div>
                    <span class='job-status-badge ${statusClass}' data-field='status-badge'>${this.escapeHtml(statusLabel)}</span>
                </div>
                <div class='job-section'>
                    <h3>Job Information</h3>
                    <div class='job-info-grid'>
                        <div class='info-item'>
                            <span class='info-label'>Type</span>
                            <span class='info-value' data-field='job-type'>${this.escapeHtml(jobTypeLabel)}</span>
                        </div>
                        <div class='info-item'>
                            <span class='info-label'>Status</span>
                            <span class='info-value' data-field='status-text'>${this.escapeHtml(statusLabel)}</span>
                        </div>
                        <div class='info-item'>
                            <span class='info-label'>Created</span>
                            <span class='info-value' data-field='created'>${this.escapeHtml(created)}</span>
                        </div>
                        <div class='info-item'>
                            <span class='info-label'>Started</span>
                            <span class='info-value' data-field='started'>${this.escapeHtml(started)}</span>
                        </div>
                        <div class='info-item'>
                            <span class='info-label'>Completed</span>
                            <span class='info-value' data-field='completed'>${this.escapeHtml(completed)}</span>
                        </div>
                        <div class='info-item'>
                            <span class='info-label'>Duration</span>
                            <span class='info-value' data-field='duration'>${this.escapeHtml(duration)}</span>
                        </div>
                    </div>
                </div>
                <div class='job-section'>
                    <h3>Request Summary</h3>
                    <div class='job-summary-grid'>
                        <div class='summary-item'>
                            <span class='summary-label'>VM name</span>
                            <span class='summary-value' data-field='vm-name'>${this.escapeHtml(vmName)}</span>
                        </div>
                        <div class='summary-item'>
                            <span class='summary-label'>Target host</span>
                            <span class='summary-value' data-field='target-host'>${this.escapeHtml(targetHost)}</span>
                        </div>
                        <div class='summary-item'>
                            <span class='summary-label'>Image</span>
                            <span class='summary-value' data-field='image'>${this.escapeHtml(imageName)}</span>
                        </div>
                    </div>
                    <button class='job-details-toggle' id='job-details-toggle' type='button'>View all details</button>
                    <div class='job-details-expanded' id='job-details-expanded' hidden>
                        <pre>${this.escapeHtml(details)}</pre>
                    </div>
                </div>
                ${childJobsSection}
                <div class='job-section'>
                    <h3>Activity log</h3>
                    <div class='job-log-toolbar'>
                        <label class='job-log-follow'>
                            <input type='checkbox' id='job-log-autoscroll' checked />
                            Follow output
                        </label>
                        <button class='job-log-copy' id='job-log-copy' type='button'>Copy</button>
                    </div>
                    <pre class='job-output'><code id='job-log-output'>${this.escapeHtml(logText)}</code></pre>
                </div>
                ${job.error ? `<div class='job-section job-error'><h3>Error</h3><div class='job-error-box'><pre>${this.escapeHtml(job.error)}</pre></div></div>` : ''}
            </div>
        `;
    }

    renderChildJobSection(childJobs = []) {
        const jobs = Array.isArray(childJobs) ? childJobs : [];
        const shouldShow = jobs.length > 0 || this.job?.job_type === 'managed_deployment';
        if (!shouldShow) {
            return '';
        }

        const content = this.renderChildJobItems(jobs);
        const fallback = '<div class="job-child-empty">Sub-jobs will appear once the deployment starts.</div>';

        return `
            <div class='job-section job-child-section'>
                <h3>Sub-jobs</h3>
                <div class='job-sub-jobs' data-field='child-jobs'>
                    ${content || fallback}
                </div>
            </div>
        `;
    }

    renderChildJobItems(childJobs = []) {
        if (!Array.isArray(childJobs) || !childJobs.length) {
            return '';
        }

        return childJobs
            .map((child) => {
                const jobId = child.job_id || '';
                const status = child.status || 'pending';
                const statusLabel = this.formatStatus(status);
                const statusClass = `job-status-badge status-${status}`;
                const jobTypeLabel = child.job_type_label || this.formatJobType(child.job_type || '');
                const vmName = child.vm_name || jobId || 'Job';
                const host = child.target_host || '—';

                return `
                    <div class='job-child-card'>
                        <div class='job-child-main'>
                            <div class='job-child-title'>${this.escapeHtml(jobTypeLabel)}</div>
                            <div class='job-child-meta'>
                                <span class='job-child-target'>${this.escapeHtml(vmName)}</span>
                                <span class='job-child-host'>on ${this.escapeHtml(host)}</span>
                                <span class='job-child-id'>ID: ${this.escapeHtml(jobId)}</span>
                            </div>
                        </div>
                        <div class='job-child-actions'>
                            <span class='${statusClass}'>${this.escapeHtml(statusLabel)}</span>
                            <button class='job-child-view' data-sub-job-id='${this.escapeHtml(jobId)}' type='button'>View</button>
                        </div>
                    </div>
                `;
            })
            .join('');
    }

    init() {
        this.rootEl = document.querySelector('.job-details');
        if (!this.rootEl) {
            return;
        }

        this.statusBadgeEl = this.rootEl.querySelector('[data-field="status-badge"]');
        this.statusTextEl = this.rootEl.querySelector('[data-field="status-text"]');
        this.jobTypeEl = this.rootEl.querySelector('[data-field="job-type"]');
        this.jobIdEl = this.rootEl.querySelector('[data-field="job-id"]');
        this.createdEl = this.rootEl.querySelector('[data-field="created"]');
        this.startedEl = this.rootEl.querySelector('[data-field="started"]');
        this.completedEl = this.rootEl.querySelector('[data-field="completed"]');
        this.durationEl = this.rootEl.querySelector('[data-field="duration"]');
        this.vmNameEl = this.rootEl.querySelector('[data-field="vm-name"]');
        this.targetHostEl = this.rootEl.querySelector('[data-field="target-host"]');
        this.imageEl = this.rootEl.querySelector('[data-field="image"]');
        this.detailsToggleEl = document.getElementById('job-details-toggle');
        this.detailsExpandedEl = document.getElementById('job-details-expanded');
        this.autoScrollInput = document.getElementById('job-log-autoscroll');
        this.copyButtonEl = document.getElementById('job-log-copy');
        this.logContainerEl = this.rootEl.querySelector('.job-output');
        this.logCodeEl = document.getElementById('job-log-output');
        this.childJobsContainer = this.rootEl.querySelector('[data-field="child-jobs"]');

        this.autoScrollInput?.addEventListener('change', (event) => {
            this.followOutput = !!event.target.checked;
        });
        this.detailsToggleEl?.addEventListener('click', () => this.toggleDetails());
        this.copyButtonEl?.addEventListener('click', () => this.copyLogs());
        this.bindChildJobLinks();

        this.refreshSummary();
        this.updateLog();

        if (this.autoSubscribe && this.jobId) {
            this.attachJobSubscription(this.jobId);
        }
    }

    handleJobMessage(message) {
        if (!message || message.job_id !== this.jobId) {
            return;
        }

        if (message.action === 'status' && message.data) {
            this.job = message.data;
            this.jobId = message.data.job_id || this.jobId;
            if (Array.isArray(message.data.output)) {
                this.logLines = [...message.data.output];
            }
            this.refreshSummary();
            this.updateLog();
        } else if (message.action === 'output' && Array.isArray(message.data?.lines)) {
            this.appendLogLines(message.data.lines);
        }
    }

    refreshSummary() {
        const job = this.job || {};
        const overlayTitle = document.getElementById('overlay-title');
        if (overlayTitle) {
            overlayTitle.textContent = this.getTitle();
        }
        if (this.jobIdEl) {
            this.jobIdEl.textContent = job.job_id || this.jobId || '—';
        }
        const statusLabel = this.formatStatus(job.status);
        if (this.statusBadgeEl) {
            this.statusBadgeEl.textContent = statusLabel;
            this.statusBadgeEl.className = `job-status-badge ${job.status ? `status-${job.status}` : 'status-pending'}`;
        }
        if (this.statusTextEl) {
            this.statusTextEl.textContent = statusLabel;
        }
        if (this.jobTypeEl) {
            this.jobTypeEl.textContent = this.formatJobType(job.job_type);
        }
        if (this.targetHostEl) {
            this.targetHostEl.textContent = job.target_host || '—';
        }
        if (this.vmNameEl) {
            this.vmNameEl.textContent = this.extractVmName(job) || '—';
        }
        if (this.imageEl) {
            this.imageEl.textContent = this.extractField(job, ['image_name', 'image']) || '—';
        }
        this.updateChildJobs();
        this.updateTiming();
        if (job.status === 'running') {
            this.startDurationTimer();
        } else {
            this.clearDurationTimer();
        }
    }

    updateLog() {
        if (!this.logCodeEl) {
            return;
        }
        if (!this.logLines.length) {
            this.logCodeEl.textContent = 'Waiting for output...';
        } else {
            this.logCodeEl.textContent = this.logLines.join('\n');
        }
        if (this.followOutput && this.logContainerEl) {
            this.logContainerEl.scrollTop = this.logContainerEl.scrollHeight;
        }
    }

    updateChildJobs() {
        const container = this.childJobsContainer || this.rootEl?.querySelector('[data-field="child-jobs"]');
        const children = Array.isArray(this.job?.child_jobs) ? this.job.child_jobs : [];
        if (!container) {
            return;
        }

        const content = this.renderChildJobItems(children);
        container.innerHTML = content || '<div class="job-child-empty">Sub-jobs will appear once the deployment starts.</div>';
        this.bindChildJobLinks();
    }

    bindChildJobLinks() {
        const buttons = this.rootEl?.querySelectorAll('[data-sub-job-id]') || [];
        buttons.forEach((button) => {
            button.addEventListener('click', async () => {
                const jobId = button.getAttribute('data-sub-job-id');
                if (jobId && typeof window.openJobDetails === 'function') {
                    await window.openJobDetails(jobId, { autoSubscribe: true });
                }
            });
        });
    }

    appendLogLines(lines) {
        if (!Array.isArray(lines) || !lines.length) {
            return;
        }
        if (!this.job) {
            this.job = { job_id: this.jobId, output: [] };
        }
        this.logLines.push(...lines);
        this.job.output = [...this.logLines];
        this.updateLog();
        this.updateTiming();
    }

    toggleDetails() {
        if (!this.detailsExpandedEl || !this.detailsToggleEl) {
            return;
        }
        const isHidden = this.detailsExpandedEl.hasAttribute('hidden');
        if (isHidden) {
            this.detailsExpandedEl.removeAttribute('hidden');
            this.detailsToggleEl.textContent = 'Hide details';
        } else {
            this.detailsExpandedEl.setAttribute('hidden', 'hidden');
            this.detailsToggleEl.textContent = 'View all details';
        }
    }

    async copyLogs() {
        if (!this.copyButtonEl || !navigator.clipboard) {
            return;
        }
        try {
            await navigator.clipboard.writeText(this.logLines.join('\n'));
            this.copyButtonEl.classList.add('copied');
            setTimeout(() => this.copyButtonEl?.classList.remove('copied'), 1500);
        } catch (error) {
            console.error('Failed to copy job output:', error);
        }
    }

    attachJobSubscription(jobId) {
        if (!jobId || typeof window.subscribeToJobUpdates !== 'function') {
            return;
        }
        if (this.jobSubscription && this.jobId) {
            this.detachJobSubscription();
        }
        this.jobId = jobId;
        this.jobSubscription = (message) => this.handleJobMessage(message);
        window.subscribeToJobUpdates(jobId, this.jobSubscription);
    }

    detachJobSubscription() {
        if (this.jobSubscription && this.jobId && typeof window.unsubscribeFromJobUpdates === 'function') {
            window.unsubscribeFromJobUpdates(this.jobId, this.jobSubscription);
        }
        this.jobSubscription = null;
    }

    startDurationTimer() {
        this.clearDurationTimer();
        if (!this.job || this.job.status !== 'running') {
            return;
        }
        this.durationTimer = setInterval(() => this.updateTiming(), 1000);
    }

    clearDurationTimer() {
        if (this.durationTimer) {
            clearInterval(this.durationTimer);
            this.durationTimer = null;
        }
    }

    updateTiming() {
        const job = this.job || {};
        if (this.createdEl) {
            this.createdEl.textContent = this.formatTimestamp(job.created_at);
        }
        if (this.startedEl) {
            this.startedEl.textContent = this.formatTimestamp(job.started_at);
        }
        if (this.completedEl) {
            this.completedEl.textContent = this.formatCompletion(job);
        }
        if (this.durationEl) {
            this.durationEl.textContent = this.computeDuration(job);
        }
    }

    cleanup() {
        this.clearDurationTimer();
        this.detachJobSubscription();
    }

    formatStatus(status) {
        const mapping = {
            pending: 'Queued',
            running: 'Running',
            completed: 'Completed',
            failed: 'Failed',
        };
        return mapping[status] || (status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Unknown');
    }

    formatTimestamp(value) {
        if (!value) {
            return '—';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        return date.toLocaleString();
    }

    formatCompletion(job) {
        if (job.completed_at) {
            return this.formatTimestamp(job.completed_at);
        }
        if (job.status === 'running') {
            return 'In progress';
        }
        return '—';
    }

    computeDuration(job) {
        const start = job.started_at ? new Date(job.started_at) : null;
        if (!start || Number.isNaN(start.getTime())) {
            return '—';
        }
        const end = job.completed_at ? new Date(job.completed_at) : (job.status === 'running' ? new Date() : null);
        const endDate = end && !Number.isNaN(end.getTime()) ? end : new Date();
        const diff = endDate.getTime() - start.getTime();
        if (diff <= 0) {
            return '—';
        }
        const totalSeconds = Math.floor(diff / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        const parts = [];
        if (hours) {
            parts.push(`${hours}h`);
        }
        if (minutes || hours) {
            parts.push(`${minutes}m`);
        }
        parts.push(`${seconds}s`);
        return parts.join(' ');
    }

    formatJobType(jobType) {
        if (!jobType) {
            return 'Unknown';
        }
        const labels = {
            managed_deployment: 'Managed Deployment',
            create_vm: 'Create VM',
            create_vm: 'Create VM',
            delete_vm: 'Delete VM',
            create_disk: 'Create Disk',
            update_vm: 'Update VM',
            update_disk: 'Update Disk',
            update_nic: 'Update NIC',
            delete_disk: 'Delete Disk',
            delete_nic: 'Delete NIC',
            create_nic: 'Create NIC',
            initialize_vm: 'Initialize VM',
        };
        if (labels[jobType]) {
            return labels[jobType];
        }
        return jobType
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (char) => char.toUpperCase());
    }

    extractVmName(job) {
        return this.extractField(job, ['vm_name', 'name']);
    }

    extractField(job, fieldNames) {
        if (!job) {
            return null;
        }
        const parameters = job.parameters || {};
        const sources = [parameters.definition?.fields, parameters.fields, parameters];
        for (const source of sources) {
            if (!source) {
                continue;
            }
            for (const field of fieldNames) {
                const value = source[field];
                if (typeof value === 'string' && value.trim()) {
                    return value.trim();
                }
            }
        }
        return null;
    }
}

// Notifications Overlay
class NotificationsOverlay extends BaseOverlay {
    getTitle() {
        return 'Notifications';
    }

    async render() {
        const notifications = await this.fetchNotifications();

        return `
            <div class="notifications-list">
                ${notifications.length === 0 ? 
                    '<p class="empty">No notifications</p>' :
                    notifications.map(n => this.renderNotification(n)).join('')
                }
            </div>

            <div class="settings-actions">
                <button class="btn btn-secondary" onclick="notificationsOverlay.clearAll()">Clear All</button>
            </div>
        `;
    }

    renderNotification(notification) {
        return `
            <div class="notification-item ${notification.read ? 'read' : 'unread'}" data-id="${notification.id}">
                <div class="notification-icon">${this.getIcon(notification.type)}</div>
                <div class="notification-content">
                    <div class="notification-title">${notification.title}</div>
                    <div class="notification-message">${notification.message}</div>
                    <div class="notification-time">${new Date(notification.timestamp).toLocaleString()}</div>
                </div>
                ${notification.actionable ? 
                    `<button class="notification-action" onclick="notificationsOverlay.handleAction('${notification.id}')">View</button>` : 
                    ''
                }
            </div>
        `;
    }

    getIcon(type) {
        const icons = {
            'success': '✅',
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️',
            'job': '⚙️'
        };
        return icons[type] || 'ℹ️';
    }

    async fetchNotifications() {
        // Placeholder - would fetch from API
        return [
            {
                id: '1',
                type: 'success',
                title: 'VM Started',
                message: 'Virtual machine "web-server-01" started successfully',
                timestamp: new Date(Date.now() - 300000).toISOString(),
                read: false,
                actionable: true
            },
            {
                id: '2',
                type: 'info',
                title: 'Inventory Refreshed',
                message: 'Inventory data refreshed for all hosts',
                timestamp: new Date(Date.now() - 600000).toISOString(),
                read: true,
                actionable: false
            }
        ];
    }

    handleAction(notificationId) {
        console.log('Handle notification action:', notificationId);
        // Would open job details or navigate to relevant view
    }

    clearAll() {
        console.log('Clear all notifications');
        overlayManager.close();
    }
}

// Disk Create Overlay
class DiskCreateOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.vmId = data.vm_id || '';
        this.vmName = data.vm_name || '';
        this.host = data.host || '';
        this.schema = null;
        this.rootEl = null;
        this.formEl = null;
        this.messagesEl = null;
    }

    getTitle() {
        return `Add Disk to ${this.vmName || 'VM'}`;
    }

    async render() {
        return `
            <div class="schema-form" id="disk-create-root">
                <div class="form-loading">Loading schema...</div>
            </div>
        `;
    }

    async init() {
        this.rootEl = document.getElementById('disk-create-root');
        if (!this.rootEl) {
            console.error('Disk create root element missing');
            return;
        }

        try {
            this.renderForm();
        } catch (error) {
            console.error('Failed to load disk creation form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load disk creation form. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        this.rootEl.innerHTML = `
            <form id="disk-create-form" class="schema-form-body">
                <div id="disk-create-messages" class="form-messages" role="alert"></div>
                <div class="schema-fields">
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="disk-size-gb" class="field-label">Disk Size (GB)</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="disk-size-gb" name="disk_size_gb" required 
                                   min="1" max="65536" value="100" step="1" inputmode="numeric" />
                        </div>
                        <p class="field-description">Size of the virtual disk in gigabytes</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="disk-type" class="field-label">Disk Type</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <select id="disk-type" name="disk_type" required>
                                <option value="Dynamic">Dynamic</option>
                                <option value="Fixed">Fixed</option>
                            </select>
                        </div>
                        <p class="field-description">Type of virtual hard disk (Dynamic or Fixed)</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="controller-type" class="field-label">Controller Type</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <select id="controller-type" name="controller_type" required>
                                <option value="SCSI">SCSI</option>
                                <option value="IDE">IDE</option>
                            </select>
                        </div>
                        <p class="field-description">Type of controller to attach the disk to</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="storage-class" class="field-label">Storage Class</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="storage-class" name="storage_class" 
                                   placeholder="e.g., fast-ssd" />
                        </div>
                        <p class="field-description">Name of the storage class where the disk will be stored (optional)</p>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="disk-create-cancel">Cancel</button>
                    <button type="submit" class="btn" id="disk-create-submit">Create Disk</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('disk-create-form');
        this.messagesEl = document.getElementById('disk-create-messages');
        const cancelBtn = document.getElementById('disk-create-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = { vm_id: this.vmId };

        // Collect form values based on Pydantic DiskSpec model
        values.disk_size_gb = parseInt(formData.get('disk_size_gb'), 10);
        values.disk_type = formData.get('disk_type');
        values.controller_type = formData.get('controller_type');
        
        const storageClass = formData.get('storage_class');
        if (storageClass && storageClass.trim()) {
            values.storage_class = storageClass.trim();
        }

        try {
            const response = await fetch('/api/v1/resources/disks', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    values: values,
                    target_host: this.host
                })
            });

            const result = await response.json();

            if (response.ok) {
                overlayManager.close();
                // Refresh the VM view
                if (window.viewManager && window.viewManager.currentViewName === 'vm') {
                    setTimeout(() => {
                        viewManager.switchView('vm', { 
                            id: this.vmId, 
                            name: this.vmName, 
                            host: this.host 
                        }, { skipHistory: true });
                    }, 100);
                }
            } else {
                const errorMsg = (result && result.detail) ? 
                    (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) : 
                    'Failed to create disk';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('Disk creation error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to create disk: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// Disk Edit Overlay
class DiskEditOverlay extends DiskCreateOverlay {
    constructor(data = {}) {
        super(data);
        this.resourceId = data.resource_id || '';
        this.resourceData = data.resource_data || {};
        this.originalDiskSize = null;  // Track original size for validation
    }

    getTitle() {
        return `Edit Disk on ${this.vmName || 'VM'}`;
    }

    async init() {
        this.rootEl = document.getElementById('disk-create-root');
        if (!this.rootEl) {
            console.error('Disk edit root element missing');
            return;
        }

        try {
            // Extract original disk size for validation
            if (this.resourceData && this.resourceData.size_gb) {
                this.originalDiskSize = parseFloat(this.resourceData.size_gb);
            }
            this.renderForm();
        } catch (error) {
            console.error('Failed to load disk edit form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load disk edit form. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        // Get current values from resource data
        const currentDiskSize = this.resourceData.size_gb || 100;
        const currentDiskType = this.resourceData.type || 'Dynamic';
        const currentControllerType = this.resourceData.controller_type || this.resourceData.controller || 'SCSI';
        const currentStorageClass = this.resourceData.storage_class || '';

        // Add notice about disk size restrictions
        const sizeNotice = this.originalDiskSize ? 
            `<p class="field-note" style="margin-bottom: 16px;">
                <strong>Note:</strong> Disk size cannot be reduced below its current size of ${this.originalDiskSize} GB.
            </p>` : '';

        this.rootEl.innerHTML = `
            <form id="disk-create-form" class="schema-form-body">
                <div id="disk-create-messages" class="form-messages" role="alert"></div>
                ${sizeNotice}
                <div class="schema-fields">
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="disk-size-gb" class="field-label">Disk Size (GB)</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="disk-size-gb" name="disk_size_gb" required 
                                   min="${this.originalDiskSize || 1}" max="65536" 
                                   value="${this.escapeHtml(currentDiskSize)}" 
                                   step="1" inputmode="numeric" 
                                   data-original-size="${this.originalDiskSize || ''}" />
                        </div>
                        <p class="field-description">Size of the virtual disk in gigabytes</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="disk-type" class="field-label">Disk Type</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <select id="disk-type" name="disk_type" required>
                                <option value="Dynamic" ${currentDiskType === 'Dynamic' ? 'selected' : ''}>Dynamic</option>
                                <option value="Fixed" ${currentDiskType === 'Fixed' ? 'selected' : ''}>Fixed</option>
                            </select>
                        </div>
                        <p class="field-description">Type of virtual hard disk (Dynamic or Fixed)</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="controller-type" class="field-label">Controller Type</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <select id="controller-type" name="controller_type" required>
                                <option value="SCSI" ${currentControllerType === 'SCSI' ? 'selected' : ''}>SCSI</option>
                                <option value="IDE" ${currentControllerType === 'IDE' ? 'selected' : ''}>IDE</option>
                            </select>
                        </div>
                        <p class="field-description">Type of controller to attach the disk to</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="storage-class" class="field-label">Storage Class</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="storage-class" name="storage_class" 
                                   value="${this.escapeHtml(currentStorageClass)}"
                                   placeholder="e.g., fast-ssd" />
                        </div>
                        <p class="field-description">Name of the storage class where the disk will be stored (optional)</p>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="disk-create-cancel">Cancel</button>
                    <button type="submit" class="btn" id="disk-create-submit">Update Disk</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('disk-create-form');
        this.messagesEl = document.getElementById('disk-create-messages');
        const cancelBtn = document.getElementById('disk-create-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = { vm_id: this.vmId };

        // Collect form values based on Pydantic DiskSpec model
        values.disk_size_gb = parseInt(formData.get('disk_size_gb'), 10);
        values.disk_type = formData.get('disk_type');
        values.controller_type = formData.get('controller_type');
        
        const storageClass = formData.get('storage_class');
        if (storageClass && storageClass.trim()) {
            values.storage_class = storageClass.trim();
        }

        // Client-side validation: prevent disk shrinking
        if (values.disk_size_gb && this.originalDiskSize && values.disk_size_gb < this.originalDiskSize) {
            this.messagesEl.innerHTML = `<div class="form-error">Disk size cannot be reduced below its current size of ${this.originalDiskSize} GB.</div>`;
            return;
        }

        try {
            const response = await fetch(`/api/v1/resources/vms/${encodeURIComponent(this.vmId)}/disks/${encodeURIComponent(this.resourceId)}`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    values: values,
                    target_host: this.host,
                    resource_id: this.resourceId
                })
            });

            const result = await response.json();

            if (response.ok) {
                overlayManager.close();
                if (window.viewManager && window.viewManager.currentViewName === 'vm') {
                    setTimeout(() => {
                        viewManager.switchView('vm', { 
                            id: this.vmId, 
                            name: this.vmName, 
                            host: this.host 
                        }, { skipHistory: true });
                    }, 100);
                }
            } else {
                const errorMsg = (result && result.detail) ? 
                    (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) : 
                    'Failed to update disk';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('Disk update error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to update disk: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// NIC Create Overlay
class NicCreateOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.vmId = data.vm_id || '';
        this.vmName = data.vm_name || '';
        this.host = data.host || '';
        this.schema = null;
        this.rootEl = null;
        this.formEl = null;
        this.messagesEl = null;
    }

    getTitle() {
        return `Add Network Adapter to ${this.vmName || 'VM'}`;
    }

    async render() {
        return `
            <div class="schema-form" id="nic-create-root">
                <div class="form-loading">Loading schema...</div>
            </div>
        `;
    }

    async init() {
        this.rootEl = document.getElementById('nic-create-root');
        if (!this.rootEl) {
            console.error('NIC create root element missing');
            return;
        }

        try {
            this.renderForm();
        } catch (error) {
            console.error('Failed to load NIC creation form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load network adapter creation form. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        this.rootEl.innerHTML = `
            <form id="nic-create-form" class="schema-form-body">
                <div id="nic-create-messages" class="form-messages" role="alert"></div>
                <div class="schema-fields">
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="network" class="field-label">Network</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="network" name="network" required 
                                   placeholder="e.g., Production" />
                        </div>
                        <p class="field-description">Name of the network to connect the adapter to</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="adapter-name" class="field-label">Adapter Name</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="adapter-name" name="adapter_name" 
                                   placeholder="e.g., Network Adapter 2" />
                        </div>
                        <p class="field-description">Optional name for the network adapter</p>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="nic-create-cancel">Cancel</button>
                    <button type="submit" class="btn" id="nic-create-submit">Create Network Adapter</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('nic-create-form');
        this.messagesEl = document.getElementById('nic-create-messages');
        const cancelBtn = document.getElementById('nic-create-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = { vm_id: this.vmId };

        // Collect form values based on Pydantic NicSpec model
        values.network = formData.get('network');
        
        const adapterName = formData.get('adapter_name');
        if (adapterName && adapterName.trim()) {
            values.adapter_name = adapterName.trim();
        }

        try {
            const response = await fetch('/api/v1/resources/nics', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    values: values,
                    target_host: this.host
                })
            });

            const result = await response.json();

            if (response.ok) {
                overlayManager.close();
                if (window.viewManager && window.viewManager.currentViewName === 'vm') {
                    setTimeout(() => {
                        viewManager.switchView('vm', { 
                            id: this.vmId, 
                            name: this.vmName, 
                            host: this.host 
                        }, { skipHistory: true });
                    }, 100);
                }
            } else {
                const errorMsg = (result && result.detail) ? 
                    (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) : 
                    'Failed to create network adapter';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('NIC creation error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to create network adapter: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// NIC Edit Overlay
class NicEditOverlay extends NicCreateOverlay {
    constructor(data = {}) {
        super(data);
        this.resourceId = data.resource_id || '';
        this.resourceData = data.resource_data || {};
    }

    getTitle() {
        return `Edit Network Adapter on ${this.vmName || 'VM'}`;
    }

    async init() {
        this.rootEl = document.getElementById('nic-create-root');
        if (!this.rootEl) {
            console.error('NIC edit root element missing');
            return;
        }

        try {
            this.renderForm();
        } catch (error) {
            console.error('Failed to load NIC edit form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load network adapter edit form. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        // Get current values from resource data
        const currentNetwork = this.resourceData.network_name || this.resourceData.network || this.resourceData.virtual_switch || '';
        const currentAdapterName = this.resourceData.adapter_name || this.resourceData.name || '';

        this.rootEl.innerHTML = `
            <form id="nic-create-form" class="schema-form-body">
                <div id="nic-create-messages" class="form-messages" role="alert"></div>
                <div class="schema-fields">
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="network" class="field-label">Network</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="network" name="network" required 
                                   value="${this.escapeHtml(currentNetwork)}"
                                   placeholder="e.g., Production" />
                        </div>
                        <p class="field-description">Name of the network to connect the adapter to</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="adapter-name" class="field-label">Adapter Name</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="adapter-name" name="adapter_name" 
                                   value="${this.escapeHtml(currentAdapterName)}"
                                   placeholder="e.g., Network Adapter 2" />
                        </div>
                        <p class="field-description">Optional name for the network adapter</p>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="nic-create-cancel">Cancel</button>
                    <button type="submit" class="btn" id="nic-create-submit">Update Network Adapter</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('nic-create-form');
        this.messagesEl = document.getElementById('nic-create-messages');
        const cancelBtn = document.getElementById('nic-create-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = { vm_id: this.vmId };

        // Collect form values based on Pydantic NicSpec model
        values.network = formData.get('network');
        
        const adapterName = formData.get('adapter_name');
        if (adapterName && adapterName.trim()) {
            values.adapter_name = adapterName.trim();
        }

        // Client-side validation: ensure network is specified
        if (!values.network?.trim()) {
            this.messagesEl.innerHTML = `<div class="form-error">Network name is required.</div>`;
            return;
        }

        try {
            const response = await fetch(`/api/v1/resources/vms/${encodeURIComponent(this.vmId)}/nics/${encodeURIComponent(this.resourceId)}`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    values: values,
                    target_host: this.host,
                    resource_id: this.resourceId
                })
            });

            const result = await response.json();

            if (response.ok) {
                overlayManager.close();
                if (window.viewManager && window.viewManager.currentViewName === 'vm') {
                    setTimeout(() => {
                        viewManager.switchView('vm', { 
                            id: this.vmId, 
                            name: this.vmName, 
                            host: this.host 
                        }, { skipHistory: true });
                    }, 100);
                }
            } else {
                const errorMsg = (result && result.detail) ? 
                    (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) : 
                    'Failed to update network adapter';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('NIC update error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to update network adapter: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// VM Edit Overlay
class VMEditOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.vmId = data.vm_id || '';
        this.vmName = data.vm_name || '';
        this.host = data.host || '';
        this.vmData = data.vm_data || {};
        this.schema = null;
        this.rootEl = null;
        this.formEl = null;
        this.messagesEl = null;
    }

    getTitle() {
        return `Edit ${this.vmName || 'VM'}`;
    }

    async render() {
        return `
            <div class="schema-form" id="vm-edit-root">
                <div class="form-loading">Loading schema...</div>
            </div>
        `;
    }

    async init() {
        this.rootEl = document.getElementById('vm-edit-root');
        if (!this.rootEl) {
            console.error('VM edit root element missing');
            return;
        }

        try {
            this.schema = await this.fetchSchema();
            this.renderForm();
        } catch (error) {
            console.error('Failed to load VM schema:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load VM edit form. Please try again later.</div>
            `;
        }
    }

    async fetchSchema() {
        const response = await fetch('/api/v1/schema/vm-create', { credentials: 'same-origin' });
        if (!response.ok) {
            throw new Error(`Schema request failed: ${response.status}`);
        }
        return await response.json();
    }

    renderForm() {
        if (!this.schema) return;

        // Filter out guest_config fields for VM edit (only hardware fields)
        const fieldsHtml = this.schema.fields
            .filter(field => !field.guest_config && field.id !== 'vm_name')
            .map(field => this.renderField(field))
            .join('');

        this.rootEl.innerHTML = `
            <form id="vm-edit-form" class="schema-form-body">
                <div id="vm-edit-messages" class="form-messages" role="alert"></div>
                <p class="field-note">Note: You can only modify hardware properties. Guest configuration (hostname, domain join, etc.) is set during initial provisioning.</p>
                <div class="schema-fields">${fieldsHtml}</div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="vm-edit-cancel">Cancel</button>
                    <button type="submit" class="btn" id="vm-edit-submit">Update VM</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('vm-edit-form');
        this.messagesEl = document.getElementById('vm-edit-messages');
        const cancelBtn = document.getElementById('vm-edit-cancel');

        cancelBtn?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    renderField(field) {
        const fieldId = `schema-${field.id}`;
        const requiredPill = field.required ? '<span class="field-required-pill">Required</span>' : '';
        const labelText = this.escapeHtml(field.label || field.id);
        const description = field.description ? `<p class="field-description">${this.escapeHtml(field.description)}</p>` : '';
        const inputControl = this.renderInputControl(field, fieldId);

        return `
            <div class="schema-field" data-field-id="${field.id}">
                <div class="field-header">
                    <div class="field-title">
                        <label for="${fieldId}" class="field-label">${labelText}</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">${inputControl}</div>
                ${description}
            </div>
        `;
    }

    renderInputControl(field, fieldId) {
        const type = (field.type || 'string').toLowerCase();
        const validations = field.validations || {};
        const requiredAttr = field.required ? 'required' : '';
        const placeholder = field.hint ? `placeholder="${this.escapeHtml(field.hint)}"` : '';
        
        // Map VM data fields to schema fields
        let currentValue;
        if (field.id === 'cpu_cores') {
            currentValue = this.vmData.cpu_cores ?? field.default ?? '';
        } else if (field.id === 'gb_ram') {
            // Schema uses gb_ram but VM data exposes memory_gb
            currentValue = this.vmData.memory_gb ?? this.vmData.memory_startup_gb ?? field.default ?? '';
        } else if (field.id === 'memory_gb') {
            currentValue = this.vmData.memory_gb ?? this.vmData.memory_startup_gb ?? field.default ?? '';
        } else if (field.id === 'memory_startup_gb') {
            currentValue = this.vmData.memory_startup_gb ?? field.default ?? '';
        } else if (field.id === 'memory_min_gb') {
            currentValue = this.vmData.memory_min_gb ?? field.default ?? '';
        } else if (field.id === 'memory_max_gb') {
            currentValue = this.vmData.memory_max_gb ?? field.default ?? '';
        } else if (field.id === 'dynamic_memory_enabled') {
            currentValue = this.vmData.dynamic_memory_enabled ?? field.default ?? false;
        } else {
            currentValue = this.vmData[field.id] ?? field.default ?? '';
        }

        if (type === 'boolean') {
            const checked = currentValue === true ? 'checked' : '';
            return `
                <label class="checkbox-field">
                    <input type="checkbox" id="${fieldId}" name="${field.id}" ${checked} />
                    <span>Enable</span>
                </label>
            `;
        }

        if (type === 'integer') {
            const min = validations.minimum !== undefined ? `min="${validations.minimum}"` : '';
            const max = validations.maximum !== undefined ? `max="${validations.maximum}"` : '';
            const valueAttr = currentValue !== '' ? `value="${this.escapeHtml(currentValue)}"` : '';
            return `<input type="number" inputmode="numeric" step="1" id="${fieldId}" name="${field.id}" ${min} ${max} ${placeholder} ${valueAttr} ${requiredAttr} />`;
        }

        if (type === 'multiline') {
            return `<textarea id="${fieldId}" name="${field.id}" rows="4" ${placeholder} ${requiredAttr}>${this.escapeHtml(currentValue)}</textarea>`;
        }

        const inputType = type === 'secret' ? 'password' : 'text';
        const patternValue = validations.pattern ? this.escapeHtml(validations.pattern) : '';
        const pattern = patternValue ? `pattern="${patternValue}"` : '';
        const valueAttr = currentValue !== '' ? `value="${this.escapeHtml(currentValue)}"` : '';
        return `<input type="${inputType}" id="${fieldId}" name="${field.id}" ${pattern} ${placeholder} ${valueAttr} ${requiredAttr} />`;
    }

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = {};

        for (const [key, value] of formData.entries()) {
            const field = this.schema.fields.find(f => f.id === key);
            if (!field) continue;

            if (field.type === 'integer') {
                values[key] = parseInt(value, 10);
            } else if (field.type === 'boolean') {
                values[key] = formData.has(key);
            } else {
                values[key] = value;
            }
        }

        try {
            const response = await fetch(`/api/v1/resources/vms/${encodeURIComponent(this.vmId)}`, {
                method: 'PUT',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    schema_version: this.schema.version || 1,
                    values: values,
                    target_host: this.host
                })
            });

            const result = await response.json();

            if (response.ok) {
                overlayManager.close();
                if (window.viewManager && window.viewManager.currentViewName === 'vm') {
                    setTimeout(() => {
                        viewManager.switchView('vm', { 
                            id: this.vmId, 
                            name: this.vmName, 
                            host: this.host 
                        }, { skipHistory: true });
                    }, 100);
                }
            } else {
                const errorMsg = (result && result.detail) ? 
                    (typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)) : 
                    'Failed to update VM';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('VM update error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to update VM: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// Initialize overlay manager
const overlayManager = new OverlayManager();

// Export for use in save functions
const settingsOverlay = new SettingsOverlay();
const notificationsOverlay = new NotificationsOverlay();
