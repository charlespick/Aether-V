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
    getTitle() {
        return 'Settings';
    }

    async render() {
        const aboutData = await this.fetchAboutInfo();
        const build = aboutData?.build || {};
        const productName = this.escapeHtml(aboutData?.name || 'Aether-V Orchestrator');
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
        ].filter(item => item.value);

        const detailMarkup = details.length
            ? details.map(item => `
                <div class="about-item">
                    <span class="about-label">${this.escapeHtml(item.label)}</span>
                    <span class="about-value">${this.escapeHtml(String(item.value))}</span>
                </div>
            `).join('')
            : '<p class="empty">Build metadata unavailable.</p>';

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
                    <p><strong>${productName}</strong></p>
                    <p>${description}</p>
                    <div class="about-grid">
                        ${detailMarkup}
                    </div>
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

    formatBuildTime(value) {
        if (!value) return null;
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return parsed.toUTCString();
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
}

class ProvisionJobOverlay extends BaseOverlay {
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
        return 'Create Virtual Machine';
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
        const response = await fetch('/api/v1/schema/job-inputs', { credentials: 'same-origin' });
        if (!response.ok) {
            throw new Error(`Schema request failed: ${response.status}`);
        }
        return response.json();
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
        const description = vmField.description ? `<p class="field-description">${this.escapeHtml(vmField.description)}</p>` : '';
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
            return `<input type="number" inputmode="numeric" step="1" id="${fieldId}" name="${field.id}" ${min} ${max} ${valueAttr} ${requiredAttr} />`;
        }

        if (type === 'multiline') {
            return `<textarea id="${fieldId}" name="${field.id}" rows="4" ${requiredAttr}>${this.escapeHtml(defaultValue)}</textarea>`;
        }

        const inputType = type === 'secret' ? 'password' : 'text';
        const patternValue = validations.pattern ? this.escapeHtml(validations.pattern) : '';
        const pattern = patternValue ? `pattern="${patternValue}"` : '';
        const valueAttr = defaultValue !== '' ? `value="${this.escapeHtml(defaultValue)}"` : '';
        const placeholder = type === 'ipv4' ? 'placeholder="192.0.2.10"' : '';
        return `<input type="${inputType}" id="${fieldId}" name="${field.id}" ${pattern} ${placeholder} ${valueAttr} ${requiredAttr} />`;
    }

    renderParameterSets() {
        const parameterSets = this.schema?.parameter_sets || [];
        if (!parameterSets.length) {
            return '';
        }

        const rows = parameterSets.map((set) => `
            <div class="parameter-set">
                <div class="parameter-set-title">${this.escapeHtml(set.label || set.id)}</div>
                <div class="parameter-set-mode">Mode: ${this.escapeHtml(set.mode || 'unspecified')}</div>
                <div class="parameter-set-description">${this.escapeHtml(set.description || '')}</div>
                <div class="parameter-set-members">Fields: ${this.escapeHtml((set.members || []).join(', '))}</div>
            </div>
        `).join('');

        return `
            <div class="parameter-set-summary">
                <h3>Parameter Sets</h3>
                ${rows}
            </div>
        `;
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
            const response = await fetch('/api/v1/jobs/provision', {
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
    }

    getTitle() {
        const job = this.job;
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

        return `
            <div class='job-details' data-job-id='${this.escapeHtml(jobId)}'>
                <div class='job-header'>
                    <div class='job-header-text'>
                        <div class='job-title'>${this.escapeHtml(this.getTitle())}</div>
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

        this.autoScrollInput?.addEventListener('change', (event) => {
            this.followOutput = !!event.target.checked;
        });
        this.detailsToggleEl?.addEventListener('click', () => this.toggleDetails());
        this.copyButtonEl?.addEventListener('click', () => this.copyLogs());

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
        if (jobType === 'provision_vm') {
            return 'Create VM';
        }
        if (jobType === 'delete_vm') {
            return 'Delete VM';
        }
        return jobType.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
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

// Initialize overlay manager
const overlayManager = new OverlayManager();

// Export for use in save functions
const settingsOverlay = new SettingsOverlay();
const notificationsOverlay = new NotificationsOverlay();
