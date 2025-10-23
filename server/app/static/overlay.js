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
}

// Settings Overlay
class SettingsOverlay extends BaseOverlay {
    getTitle() {
        return 'Settings';
    }

    async render() {
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
                    <p><strong>Aether-V Orchestrator</strong></p>
                    <p>Version: 0.1.0</p>
                    <p>Hyper-V Virtual Machine Management Platform</p>
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
}

class ProvisionJobOverlay extends BaseOverlay {
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
        this.schema = (this.data?.schema) || window.jobSchema || (window.appConfig?.job_schema) || null;
        this.rootEl = document.getElementById('provision-job-root');
        if (!this.rootEl) {
            console.error('Provision job root element missing');
            return;
        }

        if (this.schema) {
            this.renderForm();
        } else {
            this.loadSchema();
        }
    }

    async loadSchema() {
        try {
            const response = await fetch('/api/v1/schema/job-inputs', { credentials: 'same-origin' });
            if (!response.ok) {
                throw new Error(`Schema request failed: ${response.status}`);
            }
            this.schema = await response.json();
            window.jobSchema = this.schema;
            this.renderForm();
        } catch (error) {
            console.error('Failed to load job schema:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load job schema. Please try again later.</div>
            `;
        }
    }

    renderForm() {
        if (!this.schema) {
            return;
        }

        const fieldSetMap = this.buildParameterSetMap();
        const fieldsHtml = this.schema.fields
            .map(field => this.renderField(field, fieldSetMap.get(field.id) || []))
            .join('');

        const parameterSetHtml = this.renderParameterSets();

        this.rootEl.innerHTML = `
            <form id="provision-job-form" class="schema-form-body">
                <div id="provision-job-messages" class="form-messages" role="alert"></div>
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
        const isRequired = field.required ? '<span class="field-required" aria-hidden="true">*</span>' : '<span class="field-optional">Optional</span>';
        const description = field.description ? `<p class="field-description">${field.description}</p>` : '';
        const tags = this.renderFieldTags(field, parameterSets);
        const inputControl = this.renderInputControl(field, fieldId);

        return `
            <div class="schema-field" data-field-id="${field.id}">
                <div class="field-header">
                    <label for="${fieldId}" class="field-label">${field.label || field.id}${isRequired}</label>
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
                tags.push(`<span class="field-tag">${set.label || set.id}</span>`);
            });
        }

        const applicability = field.applicability;
        if (applicability?.os_family) {
            const families = applicability.os_family.map((fam) => fam.charAt(0).toUpperCase() + fam.slice(1));
            tags.push(`<span class="field-tag field-tag-muted">${families.join(', ')} only</span>`);
        }

        if (!tags.length) {
            return '';
        }

        return `<div class="field-tags">${tags.join('')}</div>`;
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
            const valueAttr = defaultValue !== '' ? `value="${defaultValue}"` : '';
            return `<input type="number" inputmode="numeric" step="1" id="${fieldId}" name="${field.id}" ${min} ${max} ${valueAttr} ${requiredAttr} />`;
        }

        if (type === 'multiline') {
            return `<textarea id="${fieldId}" name="${field.id}" rows="4" ${requiredAttr}>${defaultValue}</textarea>`;
        }

        const inputType = type === 'secret' ? 'password' : 'text';
        const pattern = type === 'ipv4' ? 'pattern="^(?:\\d{1,3}\\.){3}\\d{1,3}$"' : '';
        const valueAttr = defaultValue !== '' ? `value="${defaultValue}"` : '';
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
                <div class="parameter-set-title">${set.label || set.id}</div>
                <div class="parameter-set-mode">Mode: ${set.mode || 'unspecified'}</div>
                <div class="parameter-set-description">${set.description || ''}</div>
                <div class="parameter-set-members">Fields: ${(set.members || []).join(', ')}</div>
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
                    values: payload
                })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                const errorMessages = this.extractErrorMessages(error);
                this.showMessage(errorMessages.join('<br>') || 'Failed to submit job.', 'error');
                return;
            }

            const job = await response.json();
            this.showMessage(`Job ${job.job_id} queued successfully.`, 'success');
            setTimeout(() => overlayManager.close(), 1500);
        } catch (error) {
            console.error('Failed to submit provisioning job:', error);
            this.showMessage('Unexpected error submitting job.', 'error');
        } finally {
            submitBtn?.removeAttribute('disabled');
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

        this.messagesEl.classList.remove('error', 'success');
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

        this.messagesEl.innerHTML = message;
    }
}

// Job Details Overlay
class JobDetailsOverlay extends BaseOverlay {
    getTitle() {
        return 'Job Details';
    }

    async render() {
        const job = this.data.job || {};
        
        return `
            <div class="job-details">
                <div class="job-header">
                    <span class="job-status ${job.status || 'pending'}">${job.status || 'Unknown'}</span>
                    <span class="job-id">Job #${job.id || 'N/A'}</span>
                </div>

                <div class="job-section">
                    <h3>Job Information</h3>
                    <div class="info-grid">
                        <div class="info-item">
                            <span class="info-label">Type:</span>
                            <span>${job.type || 'Unknown'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Started:</span>
                            <span>${job.started ? new Date(job.started).toLocaleString() : 'N/A'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Completed:</span>
                            <span>${job.completed ? new Date(job.completed).toLocaleString() : 'In progress'}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Duration:</span>
                            <span>${job.duration || 'N/A'}</span>
                        </div>
                    </div>
                </div>

                <div class="job-section">
                    <h3>Output</h3>
                    <div class="job-output">
                        <pre>${job.output || 'No output available'}</pre>
                    </div>
                </div>

                ${job.error ? `
                <div class="job-section">
                    <h3>Error</h3>
                    <div class="job-error">
                        <pre>${job.error}</pre>
                    </div>
                </div>
                ` : ''}
            </div>
        `;
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
