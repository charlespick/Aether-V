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
        this.registerOverlay('oss-attributions', OSSAttributionsOverlay);
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
                        />
                        <div class="about-brand-text">
                            <p class="about-name">${productName}</p>
                            <p class="about-description">${description}</p>
                        </div>
                    </div>
                    ${summaryMarkup}
                    ${moreDetailsMarkup}
                    ${seeMoreButtonMarkup}
                    <div class="about-actions-row">
                        <button
                            type="button"
                            class="btn btn-secondary"
                            id="oss-attributions-btn"
                        >
                            OSS Attributions
                        </button>
                    </div>
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

        const ossAttributionsBtn = document.getElementById('oss-attributions-btn');
        if (ossAttributionsBtn) {
            this.ossAttributionsHandler = () => {
                overlayManager.close();
                overlayManager.open('oss-attributions');
            };
            ossAttributionsBtn.addEventListener('click', this.ossAttributionsHandler);
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

        if (this.ossAttributionsHandler) {
            const ossAttributionsBtn = document.getElementById('oss-attributions-btn');
            if (ossAttributionsBtn) {
                ossAttributionsBtn.removeEventListener('click', this.ossAttributionsHandler);
            }
            this.ossAttributionsHandler = null;
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
        
        // Use enriched metadata if available for better resource naming
        const metadata = job.parameters?._metadata || {};
        const resourceType = metadata.resource_type || '';
        const resourceName = metadata.resource_name || this.extractVmName(job) || job.job_id || 'Job';
        
        const label = this.formatJobType(job.job_type);
        
        // Format: <Operation> <Resource Type> • <Resource Name>
        // For VM jobs, resource_type will be "VM", so we get "Delete VM • vm-name"
        // For NIC jobs, we get "Delete Network Adapter • NIC-Prod-01"
        // For Disk jobs, we get "Create Disk • data-disk-01"
        
        return `${label} • ${resourceName}`;
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
        const isManagedDeployment = job.job_type === 'managed_deployment';

        // For managed deployment, show deployment steps instead of activity log
        const activitySection = isManagedDeployment ? 
            this.renderManagedDeploymentSteps(job) :
            `<div class='job-section'>
                <h3>Activity log</h3>
                <div class='job-log-toolbar'>
                    <label class='job-log-follow'>
                        <input type='checkbox' id='job-log-autoscroll' checked />
                        Follow output
                    </label>
                    <button class='job-log-copy' id='job-log-copy' type='button'>Copy</button>
                </div>
                <pre class='job-output'><code id='job-log-output'>${this.escapeHtml(logText)}</code></pre>
            </div>`;

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
                ${activitySection}
                ${job.error ? `<div class='job-section job-error'><h3>Error</h3><div class='job-error-box'><pre>${this.escapeHtml(job.error)}</pre></div></div>` : ''}
            </div>
        `;
    }

    renderManagedDeploymentSteps(job = this.job) {
        if (!job) {
            return '';
        }

        const stepsHtml = this.renderManagedDeploymentStepsContent(job);

        return `
            <div class='job-section deployment-steps-section'>
                <h3>Deployment Steps</h3>
                <div class='deployment-steps' data-field='deployment-steps'>
                    ${stepsHtml}
                </div>
            </div>
        `;
    }

    renderChildJobSection(childJobs = []) {
        const jobs = Array.isArray(childJobs) ? childJobs : [];
        
        // Don't show Sub-jobs section for managed_deployment - use Deployment Steps instead
        const isManagedDeployment = this.job?.job_type === 'managed_deployment';
        if (isManagedDeployment) {
            return '';
        }
        
        const shouldShow = jobs.length > 0;
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
        this.updateDeploymentSteps();
        this.updateTiming();
        if (job.status === 'running') {
            this.startDurationTimer();
        } else {
            this.clearDurationTimer();
        }
    }

    updateDeploymentSteps() {
        // Only update for managed deployment jobs
        if (this.job?.job_type !== 'managed_deployment') {
            return;
        }

        const container = this.rootEl?.querySelector('[data-field="deployment-steps"]');
        if (!container) {
            return;
        }

        // Re-render the deployment steps with current state
        const stepsHtml = this.renderManagedDeploymentStepsContent(this.job);
        container.innerHTML = stepsHtml;
        this.bindChildJobLinks();
    }

    renderManagedDeploymentStepsContent(job) {
        if (!job) {
            return '';
        }

        // Define the deployment steps and their corresponding child job types
        const stepDefinitions = [
            { key: 'vm', label: 'Create VM', jobType: 'create_vm' },
            { key: 'disk', label: 'Create Disk', jobType: 'create_disk' },
            { key: 'nic', label: 'Create NIC', jobType: 'create_nic' },
            { key: 'init', label: 'Initialize Guest', jobType: 'initialize_vm' }
        ];

        const childJobs = Array.isArray(job.child_jobs) ? job.child_jobs : [];
        
        // Map each step to its corresponding child job and determine status
        const stepStatuses = stepDefinitions.map(step => {
            // Find the child job for this step
            const childJob = childJobs.find(child => child.job_type === step.jobType);
            
            let status = 'pending';
            let statusClass = 'status-pending';
            let childJobId = null;
            
            if (childJob) {
                // Use the actual child job status
                status = childJob.status || 'pending';
                statusClass = `status-${status}`;
                childJobId = childJob.job_id;
            }
            
            return {
                ...step,
                status,
                statusClass,
                childJobId
            };
        });

        return stepStatuses.map(step => {
            const buttonHtml = step.childJobId ? 
                `<button class='job-child-view' data-sub-job-id='${this.escapeHtml(step.childJobId)}' type='button'>View</button>` :
                '';
            
            return `
                <div class='deployment-step'>
                    <div class='step-info'>
                        <div class='step-label'>${this.escapeHtml(step.label)}</div>
                        <span class='job-status-badge ${step.statusClass}'>${this.escapeHtml(step.status)}</span>
                    </div>
                    ${buttonHtml}
                </div>
            `;
        }).join('');
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
        // Try enriched metadata first for accurate VM names
        if (job?.parameters?._metadata?.vm_name) {
            return job.parameters._metadata.vm_name;
        }
        return this.extractField(job, ['vm_name', 'name']);
    }

    extractField(job, fieldNames) {
        if (!job) {
            return null;
        }
        
        // Check enriched metadata first
        const metadata = job.parameters?._metadata || {};
        for (const field of fieldNames) {
            const value = metadata[field];
            if (typeof value === 'string' && value.trim()) {
                return value.trim();
            }
        }
        
        // Fallback to original logic
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
                <div class="form-loading">Loading form...</div>
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
            this.renderForm();
        } catch (error) {
            console.error('Failed to load VM edit form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load VM edit form. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        // Get current values from VM data
        const currentCpuCores = this.vmData.cpu_cores ?? 2;
        const currentMemoryGb = this.vmData.memory_gb ?? this.vmData.memory_startup_gb ?? 4;
        const currentStorageClass = this.vmData.storage_class ?? '';
        const currentVmClustered = this.vmData.vm_clustered ?? false;

        this.rootEl.innerHTML = `
            <form id="vm-edit-form" class="schema-form-body">
                <div id="vm-edit-messages" class="form-messages" role="alert"></div>
                <p class="field-note" style="margin-bottom: 16px;">
                    <strong>Note:</strong> You can only modify hardware properties. Guest configuration (hostname, domain join, etc.) is set during initial provisioning.
                </p>
                <div class="schema-fields">
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="cpu-cores" class="field-label">CPU Cores</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="cpu-cores" name="cpu_cores" required 
                                   min="1" max="64" value="${this.escapeHtml(currentCpuCores)}" 
                                   step="1" inputmode="numeric" />
                        </div>
                        <p class="field-description">Number of virtual CPU cores</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="gb-ram" class="field-label">Memory (GB)</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="gb-ram" name="gb_ram" required 
                                   min="1" max="512" value="${this.escapeHtml(currentMemoryGb)}" 
                                   step="1" inputmode="numeric" />
                        </div>
                        <p class="field-description">Amount of memory to assign to the VM in gigabytes</p>
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
                        <p class="field-description">Name of the storage class where VM configuration will be stored (optional)</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="vm-clustered" class="field-label">Clustered</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <label class="checkbox-field">
                                <input type="checkbox" id="vm-clustered" name="vm_clustered" 
                                       ${currentVmClustered ? 'checked' : ''} />
                                <span>Enable clustering for this VM</span>
                            </label>
                        </div>
                        <p class="field-description">Request that the VM be registered with the Failover Cluster</p>
                    </div>
                </div>
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

    async handleSubmit(event) {
        event.preventDefault();

        const formData = new FormData(this.formEl);
        const values = {};

        // Collect form values based on Pydantic VmSpec model
        values.vm_name = this.vmName;  // VM name is not editable, use existing name
        values.cpu_cores = parseInt(formData.get('cpu_cores'), 10);
        values.gb_ram = parseInt(formData.get('gb_ram'), 10);
        values.vm_clustered = formData.has('vm_clustered');
        
        const storageClass = formData.get('storage_class');
        if (storageClass && storageClass.trim()) {
            values.storage_class = storageClass.trim();
        }

        try {
            const response = await fetch(`/api/v1/resources/vms/${encodeURIComponent(this.vmId)}`, {
                method: 'PUT',
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
                    'Failed to update VM';
                this.messagesEl.innerHTML = `<div class="form-error">${this.escapeHtml(errorMsg)}</div>`;
            }
        } catch (error) {
            console.error('VM update error:', error);
            this.messagesEl.innerHTML = `<div class="form-error">Failed to update VM: ${this.escapeHtml(error.message)}</div>`;
        }
    }
}

// OSS Attributions Overlay - Displays open source license information
class OSSAttributionsOverlay extends BaseOverlay {
    constructor(data = {}) {
        super(data);
        this.licenses = null;
        this.loading = true;
        this.error = null;
    }

    getTitle() {
        return 'Open Source Licenses';
    }

    async render() {
        // Fetch license data
        await this.fetchLicenses();

        if (this.loading) {
            return `
                <div class="oss-attributions">
                    <div class="oss-loading">Loading license information...</div>
                </div>
            `;
        }

        if (this.error) {
            return `
                <div class="oss-attributions">
                    <div class="oss-error">${this.escapeHtml(this.error)}</div>
                </div>
            `;
        }

        const packages = this.licenses?.packages || [];
        const summary = this.licenses?.summary || {};

        if (packages.length === 0) {
            return `
                <div class="oss-attributions">
                    <div class="oss-empty">No license information available.</div>
                </div>
            `;
        }

        const pythonPackages = packages.filter(p => p.ecosystem === 'python');
        const jsPackages = packages.filter(p => p.ecosystem === 'javascript');

        return `
            <div class="oss-attributions">
                <div class="oss-intro">
                    <p>This software includes open source components. We thank the authors and maintainers of these packages for their contributions to the open source community.</p>
                    <div class="oss-summary">
                        <span class="oss-summary-item"><strong>${summary.total || packages.length}</strong> packages</span>
                        <span class="oss-summary-divider">•</span>
                        <span class="oss-summary-item"><strong>${summary.python || pythonPackages.length}</strong> Python</span>
                        <span class="oss-summary-divider">•</span>
                        <span class="oss-summary-item"><strong>${summary.javascript || jsPackages.length}</strong> JavaScript</span>
                    </div>
                </div>

                ${pythonPackages.length > 0 ? `
                    <div class="oss-section">
                        <h3 class="oss-section-title">Python Packages</h3>
                        <div class="oss-package-list">
                            ${pythonPackages.map(pkg => this.renderPackage(pkg)).join('')}
                        </div>
                    </div>
                ` : ''}

                ${jsPackages.length > 0 ? `
                    <div class="oss-section">
                        <h3 class="oss-section-title">JavaScript Packages</h3>
                        <div class="oss-package-list">
                            ${jsPackages.map(pkg => this.renderPackage(pkg)).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderPackage(pkg) {
        const name = this.escapeHtml(pkg.name || 'Unknown');
        const version = this.escapeHtml(pkg.version || '');
        const license = this.escapeHtml(pkg.license || 'Unknown');
        const author = pkg.author ? this.escapeHtml(pkg.author) : null;
        const url = pkg.url || '';

        const nameDisplay = url
            ? `<a href="${this.escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="oss-package-link">${name}</a>`
            : `<span class="oss-package-name">${name}</span>`;

        return `
            <div class="oss-package">
                <div class="oss-package-header">
                    ${nameDisplay}
                    ${version ? `<span class="oss-package-version">${version}</span>` : ''}
                </div>
                <div class="oss-package-details">
                    <span class="oss-package-license">${license}</span>
                    ${author ? `<span class="oss-package-author">by ${author}</span>` : ''}
                </div>
            </div>
        `;
    }

    async fetchLicenses() {
        this.loading = true;
        this.error = null;

        try {
            const response = await fetch('/api/v1/oss-licenses', {
                credentials: 'same-origin',
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch license information: ${response.statusText}`);
            }

            this.licenses = await response.json();
        } catch (error) {
            console.error('Failed to fetch OSS licenses:', error);
            this.error = 'Unable to load license information. Please try again later.';
        } finally {
            this.loading = false;
        }
    }
}

// Initialize overlay manager
const overlayManager = new OverlayManager();

// Export for use in save functions
const settingsOverlay = new SettingsOverlay();
const notificationsOverlay = new NotificationsOverlay();
