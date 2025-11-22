/**
 * Provision Form - Pydantic-based Implementation (Phase 7)
 * 
 * This replaces the schema-driven ProvisionJobOverlay with a manually coded form
 * that uses Pydantic model metadata. All conditional UI logic (DHCP vs static IP,
 * dynamic memory, domain join, ansible) is implemented directly in code.
 */

class ProvisionFormPydantic {
    constructor(data = {}) {
        this.data = data;
        this.hosts = [];
        this.rootEl = null;
        this.formEl = null;
        this.messagesEl = null;
        this.stateListener = null;
    }

    async init() {
        this.rootEl = document.getElementById('provision-job-root');
        if (!this.rootEl) {
            console.error('Provision form root element missing');
            return;
        }

        this.rootEl.innerHTML = '<div class="form-loading">Loading form...</div>';

        this.stateListener = (event) => this.applyAvailability(event.detail);
        document.addEventListener('agentDeploymentStateChanged', this.stateListener);

        try {
            this.hosts = await this.fetchHosts();
            this.renderForm();
            this.attachConditionalLogic();
            this.applyAvailability(window.agentDeploymentState);
        } catch (error) {
            console.error('Failed to prepare provisioning form:', error);
            this.rootEl.innerHTML = `
                <div class="form-error">Unable to load provisioning form. Please try again later.</div>
            `;
        }
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
        const requiredPill = '<span class="field-required-pill">Required</span>';
        
        const hostOptions = this.hosts.length ? this.hosts
            .map((host) => {
                const hostname = this.escapeHtml(host.hostname || '');
                const cluster = host.cluster ? ` (${this.escapeHtml(host.cluster)})` : '';
                return `<option value="${hostname}">${hostname}${cluster}</option>`;
            })
            .join('') : '';

        const hostSelectorHtml = this.hosts.length ? `
            <div class="primary-field" data-primary="host">
                <div class="field-header">
                    <div class="field-title">
                        <label for="target-host" class="field-label">Destination host</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">
                    <select id="target-host" name="target_host" class="primary-select" required>
                        <option value="">Select a connected host</option>
                        ${hostOptions}
                    </select>
                </div>
                <p class="field-description field-note">Only hosts that are currently connected appear in this list.</p>
            </div>
        ` : `
            <div class="primary-field" data-primary="host">
                <div class="field-header">
                    <div class="field-title">
                        <label for="target-host" class="field-label">Destination host</label>
                        ${requiredPill}
                    </div>
                </div>
                <div class="field-control">
                    <select id="target-host" name="target_host" class="primary-select" disabled>
                        <option value="">No connected hosts available</option>
                    </select>
                </div>
                <p class="field-description field-note">Reconnect a host to enable provisioning.</p>
            </div>
        `;

        this.rootEl.innerHTML = `
            <form id="provision-job-form" class="schema-form-body">
                <div id="provision-job-messages" class="form-messages" role="alert"></div>
                
                <section class="primary-controls">
                    ${hostSelectorHtml}
                    
                    <div class="primary-field" data-primary="vm-name">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="vm-name" class="field-label">VM Name</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="vm-name" name="vm_name" required 
                                   minlength="1" maxlength="64" 
                                   placeholder="e.g., web-server-01" />
                        </div>
                        <p class="field-description">Unique name for the new virtual machine. This becomes both the VM name and guest hostname.</p>
                    </div>
                </section>

                <div class="schema-fields">
                    <!-- VM Hardware -->
                    <h3 class="section-heading">VM Hardware</h3>
                    
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="cpu-cores" class="field-label">CPU Cores</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="cpu-cores" name="cpu_cores" required 
                                   min="1" max="64" value="2" step="1" inputmode="numeric" />
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
                                   min="1" max="512" value="4" step="1" inputmode="numeric" />
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
                                   placeholder="e.g., fast-ssd" />
                        </div>
                        <p class="field-description">Name of the storage class where VM configuration will be stored (optional)</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="vm-clustered" class="field-label">Clustered VM</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <label class="checkbox-field">
                                <input type="checkbox" id="vm-clustered" name="vm_clustered" />
                                <span>Enable Failover Clustering</span>
                            </label>
                        </div>
                        <p class="field-description">Request that the new VM be registered with the Failover Cluster</p>
                    </div>

                    <!-- Disk Configuration -->
                    <h3 class="section-heading">Disk Configuration</h3>
                    
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="image-name" class="field-label">Image Name</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="image-name" name="image_name" 
                                   placeholder="e.g., Windows Server 2022" />
                        </div>
                        <p class="field-description">Name of a golden image to clone. Leave empty to create a blank disk</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="disk-size-gb" class="field-label">Disk Size (GB)</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="number" id="disk-size-gb" name="disk_size_gb" 
                                   min="1" max="65536" value="100" step="1" inputmode="numeric" />
                        </div>
                        <p class="field-description">Size of the virtual disk in gigabytes</p>
                    </div>

                    <!-- Network Configuration -->
                    <h3 class="section-heading">Network Configuration</h3>
                    
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="network" class="field-label">Virtual Network</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="network" name="network" required 
                                   placeholder="e.g., Production" />
                        </div>
                        <p class="field-description">Name of the virtual network to connect the adapter to</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="use-dhcp" class="field-label">Network Configuration Mode</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <label class="checkbox-field">
                                <input type="checkbox" id="use-dhcp" checked />
                                <span>Use DHCP (uncheck for static IP)</span>
                            </label>
                        </div>
                    </div>

                    <div id="static-ip-fields" style="display: none;">
                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-v4-ipaddr" class="field-label">Static IPv4 Address</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-v4-ipaddr" name="guest_v4_ipaddr" 
                                       pattern="^(?:\\d{1,3}\\.){3}\\d{1,3}$"
                                       placeholder="e.g., 192.168.1.100" />
                            </div>
                            <p class="field-description">Static IPv4 address to assign to the guest adapter</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-v4-cidrprefix" class="field-label">CIDR Prefix</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="number" id="guest-v4-cidrprefix" name="guest_v4_cidrprefix" 
                                       min="0" max="32" step="1" inputmode="numeric" placeholder="e.g., 24" />
                            </div>
                            <p class="field-description">CIDR prefix length (e.g., 24 for /24 subnet)</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-v4-defaultgw" class="field-label">Default Gateway</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-v4-defaultgw" name="guest_v4_defaultgw" 
                                       pattern="^(?:\\d{1,3}\\.){3}\\d{1,3}$"
                                       placeholder="e.g., 192.168.1.1" />
                            </div>
                            <p class="field-description">Default IPv4 gateway for the guest adapter</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-v4-dns1" class="field-label">Primary DNS</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-v4-dns1" name="guest_v4_dns1" 
                                       pattern="^(?:\\d{1,3}\\.){3}\\d{1,3}$"
                                       placeholder="e.g., 192.168.1.2" />
                            </div>
                            <p class="field-description">Primary IPv4 DNS server</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-v4-dns2" class="field-label">Secondary DNS</label>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-v4-dns2" name="guest_v4_dns2" 
                                       pattern="^(?:\\d{1,3}\\.){3}\\d{1,3}$"
                                       placeholder="e.g., 192.168.1.3" />
                            </div>
                            <p class="field-description">Secondary IPv4 DNS server (optional)</p>
                        </div>
                    </div>

                    <!-- Guest Configuration -->
                    <h3 class="section-heading">Guest Configuration</h3>
                    
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="guest-la-uid" class="field-label">Local Admin Username</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="text" id="guest-la-uid" name="guest_la_uid" required 
                                   placeholder="e.g., Administrator" />
                        </div>
                        <p class="field-description">Username for the guest operating system's local administrator</p>
                    </div>

                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="guest-la-pw" class="field-label">Local Admin Password</label>
                                ${requiredPill}
                            </div>
                        </div>
                        <div class="field-control">
                            <input type="password" id="guest-la-pw" name="guest_la_pw" required 
                                   autocomplete="new-password" />
                        </div>
                        <p class="field-description">Password for the guest operating system's local administrator</p>
                    </div>

                    <!-- Domain Join (optional group) -->
                    <div class="schema-field">
                        <div class="field-header">
                            <div class="field-title">
                                <label for="enable-domain-join" class="field-label">Domain Join</label>
                            </div>
                        </div>
                        <div class="field-control">
                            <label class="checkbox-field">
                                <input type="checkbox" id="enable-domain-join" />
                                <span>Join to Active Directory domain</span>
                            </label>
                        </div>
                    </div>

                    <div id="domain-join-fields" style="display: none;">
                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-domain-jointarget" class="field-label">Domain FQDN</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-domain-jointarget" name="guest_domain_jointarget" 
                                       placeholder="e.g., corp.example.com" />
                            </div>
                            <p class="field-description">Fully qualified domain name to join</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-domain-joinuid" class="field-label">Domain Join Username</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-domain-joinuid" name="guest_domain_joinuid" 
                                       placeholder="e.g., EXAMPLE\\svc_join" />
                            </div>
                            <p class="field-description">User account used to join the domain</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-domain-joinpw" class="field-label">Domain Join Password</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="password" id="guest-domain-joinpw" name="guest_domain_joinpw" 
                                       autocomplete="new-password" />
                            </div>
                            <p class="field-description">Password for the domain join account</p>
                        </div>

                        <div class="schema-field">
                            <div class="field-header">
                                <div class="field-title">
                                    <label for="guest-domain-joinou" class="field-label">Organizational Unit</label>
                                    <span class="field-required-pill conditional-required">Required</span>
                                </div>
                            </div>
                            <div class="field-control">
                                <input type="text" id="guest-domain-joinou" name="guest_domain_joinou" 
                                       placeholder="e.g., OU=Servers,DC=corp,DC=example,DC=com" />
                            </div>
                            <p class="field-description">Organizational unit path for the computer account</p>
                        </div>
                    </div>
                </div>

                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" id="provision-job-cancel">Cancel</button>
                    <button type="submit" class="btn" id="provision-job-submit">Create VM</button>
                </div>
            </form>
        `;

        this.formEl = document.getElementById('provision-job-form');
        this.messagesEl = document.getElementById('provision-job-messages');
        
        document.getElementById('provision-job-cancel')?.addEventListener('click', () => overlayManager.close());
        this.formEl?.addEventListener('submit', (event) => this.handleSubmit(event));
    }

    attachConditionalLogic() {
        // DHCP vs Static IP toggle
        const useDhcpCheckbox = document.getElementById('use-dhcp');
        const staticIpFields = document.getElementById('static-ip-fields');
        
        useDhcpCheckbox?.addEventListener('change', () => {
            const useDhcp = useDhcpCheckbox.checked;
            staticIpFields.style.display = useDhcp ? 'none' : 'block';
            
            // Toggle required attributes on static IP fields
            const staticIpInputs = staticIpFields.querySelectorAll('input[name^="guest_v4_"]');
            staticIpInputs.forEach(input => {
                if (input.name === 'guest_v4_dns2') return; // dns2 is optional
                input.required = !useDhcp;
            });
        });

        // Domain Join toggle
        const enableDomainJoinCheckbox = document.getElementById('enable-domain-join');
        const domainJoinFields = document.getElementById('domain-join-fields');
        
        enableDomainJoinCheckbox?.addEventListener('change', () => {
            const enableDomainJoin = enableDomainJoinCheckbox.checked;
            domainJoinFields.style.display = enableDomainJoin ? 'block' : 'none';
            
            // Toggle required attributes on domain join fields
            const domainJoinInputs = domainJoinFields.querySelectorAll('input');
            domainJoinInputs.forEach(input => {
                input.required = enableDomainJoin;
            });
        });
    }

    async handleSubmit(event) {
        event.preventDefault();
        
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

        if (!this.formEl.reportValidity()) {
            submitBtn?.removeAttribute('disabled');
            return;
        }

        const formData = new FormData(this.formEl);
        const targetHost = formData.get('target_host');
        
        if (!targetHost) {
            this.showMessage('Select a destination host before submitting.', 'error');
            submitBtn?.removeAttribute('disabled');
            return;
        }

        // Build Pydantic model structure
        const payload = {
            vm_spec: {
                vm_name: formData.get('vm_name'),
                gb_ram: parseInt(formData.get('gb_ram'), 10),
                cpu_cores: parseInt(formData.get('cpu_cores'), 10),
                storage_class: formData.get('storage_class') || null,
                vm_clustered: formData.has('vm_clustered')
            },
            disk_spec: {
                image_name: formData.get('image_name') || null,
                disk_size_gb: parseInt(formData.get('disk_size_gb'), 10),
                storage_class: formData.get('storage_class') || null,
                disk_type: 'Dynamic',
                controller_type: 'SCSI'
            },
            nic_spec: {
                network: formData.get('network'),
                adapter_name: null
            },
            guest_config: {
                guest_la_uid: formData.get('guest_la_uid'),
                guest_la_pw: formData.get('guest_la_pw')
            },
            target_host: targetHost
        };

        // Add static IP config if not using DHCP
        const useDhcp = document.getElementById('use-dhcp').checked;
        if (!useDhcp) {
            payload.guest_config.guest_v4_ipaddr = formData.get('guest_v4_ipaddr');
            payload.guest_config.guest_v4_cidrprefix = parseInt(formData.get('guest_v4_cidrprefix'), 10);
            payload.guest_config.guest_v4_defaultgw = formData.get('guest_v4_defaultgw');
            payload.guest_config.guest_v4_dns1 = formData.get('guest_v4_dns1');
            payload.guest_config.guest_v4_dns2 = formData.get('guest_v4_dns2') || null;
        }

        // Add domain join config if enabled
        const enableDomainJoin = document.getElementById('enable-domain-join').checked;
        if (enableDomainJoin) {
            payload.guest_config.guest_domain_jointarget = formData.get('guest_domain_jointarget');
            payload.guest_config.guest_domain_joinuid = formData.get('guest_domain_joinuid');
            payload.guest_config.guest_domain_joinpw = formData.get('guest_domain_joinpw');
            payload.guest_config.guest_domain_joinou = formData.get('guest_domain_joinou');
        }

        try {
            const response = await fetch('/api/v2/managed-deployments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
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

    extractErrorMessages(errorPayload) {
        if (!errorPayload) return [];
        if (Array.isArray(errorPayload?.detail)) {
            return errorPayload.detail.map((item) => item.msg || JSON.stringify(item));
        }
        if (typeof errorPayload.detail === 'string') {
            return [errorPayload.detail];
        }
        if (Array.isArray(errorPayload.errors)) {
            return errorPayload.errors;
        }
        return [];
    }

    showMessage(message, level) {
        if (!this.messagesEl) return;
        
        this.messagesEl.classList.remove('error', 'success', 'info');
        if (!message) {
            this.messagesEl.innerHTML = '';
            return;
        }

        if (level === 'error') this.messagesEl.classList.add('error');
        if (level === 'success') this.messagesEl.classList.add('success');
        if (level === 'info') this.messagesEl.classList.add('info');
        
        this.messagesEl.innerHTML = message;
    }

    applyAvailability(state) {
        if (typeof window.applyProvisioningAvailability === 'function') {
            window.applyProvisioningAvailability(state || window.agentDeploymentState);
        }
    }

    escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    cleanup() {
        if (this.stateListener) {
            document.removeEventListener('agentDeploymentStateChanged', this.stateListener);
            this.stateListener = null;
        }
    }
}

// Export for use in overlay.js
window.ProvisionFormPydantic = ProvisionFormPydantic;
