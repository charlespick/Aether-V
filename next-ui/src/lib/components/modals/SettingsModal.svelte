<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import FormField from '$lib/components/forms/FormField.svelte';
	import FormSection from '$lib/components/forms/FormSection.svelte';
	import FormActions from '$lib/components/forms/FormActions.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { toastStore } from '$lib/stores/toastStore';

	interface Props {
		isOpen: boolean;
		onClose: () => void;
	}

	let { isOpen = $bindable(false), onClose }: Props = $props();

	// Settings state (stored in localStorage)
	let settings = $state({
		// Navigation
		showHosts: true,

		// Display
		theme: 'dark' as 'light' | 'dark' | 'system',
		autoRefreshInterval: 60,

		// Environment info (read-only, from env or API)
		environmentName: 'Production Environment',
		serverVersion: '0.5.0',
		buildDate: '2025-12-10'
	});

	let isSubmitting = $state(false);
	let diagnosticsExpanded = $state(false);
	let isLoaded = $state(false);

	// Load settings from localStorage
	function loadSettings() {
		try {
			const stored = localStorage.getItem('aetherv-settings');
			if (stored) {
				const parsed = JSON.parse(stored);
				// Update individual properties instead of reassigning the whole object
				settings.showHosts = parsed.showHosts ?? settings.showHosts;
				settings.theme = parsed.theme ?? settings.theme;
				settings.autoRefreshInterval = parsed.autoRefreshInterval ?? settings.autoRefreshInterval;
			}
		} catch (error) {
			console.error('Failed to load settings:', error);
		}
	}

	// Save settings to localStorage
	function saveSettings() {
		try {
			localStorage.setItem(
				'aetherv-settings',
				JSON.stringify({
					showHosts: settings.showHosts,
					theme: settings.theme,
					autoRefreshInterval: settings.autoRefreshInterval
				})
			);
			toastStore.success('Settings saved successfully');
		} catch (error) {
			console.error('Failed to save settings:', error);
			toastStore.error('Failed to save settings');
		}
	}

	// Handle show hosts toggle
	function handleShowHostsChange() {
		saveSettings();
	}

	// Apply theme immediately when changed
	function handleThemeChange() {
		applyTheme(settings.theme);
		saveSettings();
	}

	// Handle auto-refresh interval change
	function handleAutoRefreshChange() {
		saveSettings();
	}

	// Apply theme to document
	function applyTheme(theme: 'light' | 'dark' | 'system') {
		if (theme === 'system') {
			const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
			document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
		} else {
			document.documentElement.setAttribute('data-theme', theme);
		}
	}

	// Handle redeploy scripts (admin only)
	async function handleRedeployScripts() {
		const confirmed = confirm(
			'This will:\n\n' +
				'• Wait for all running jobs to complete\n' +
				'• Temporarily pause VM provisioning operations\n' +
				'• Redeploy all provisioning scripts to Hyper-V hosts\n' +
				'• Restart the inventory refresh cycle\n\n' +
				'VM provisioning will be unavailable during the redeployment process.\n\n' +
				'Continue?'
		);

		if (!confirmed) return;

		isSubmitting = true;

		try {
			const response = await fetch('/api/v1/admin/redeploy-scripts', {
				method: 'POST'
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to redeploy scripts');
			}

			toastStore.success('Script redeployment initiated');
		} catch (error) {
			console.error('Failed to redeploy scripts:', error);
			toastStore.error(error instanceof Error ? error.message : 'Failed to redeploy scripts');
		} finally {
			isSubmitting = false;
		}
	}

	// Load settings once when modal first opens
	$effect(() => {
		if (isOpen && !isLoaded) {
			loadSettings();
			isLoaded = true;
		}
	});
</script>

<Modal {isOpen} {onClose} title="Settings" variant="slideOver">
	<div class="settings-content">
		<!-- Navigation Settings -->
		<FormSection title="Navigation" description="Control the navigation sidebar behavior">
			<FormField description="Show individual Hyper-V hosts in the navigation tree">
				<label class="checkbox-label">
					<input type="checkbox" bind:checked={settings.showHosts} onchange={handleShowHostsChange} />
					<span>Show Hyper-V Hosts</span>
				</label>
			</FormField>
		</FormSection>

		<!-- Display Settings -->
		<FormSection title="Display" description="Customize the appearance and refresh behavior">
			<FormField label="Theme" description="Choose the color theme for the interface">
				<select bind:value={settings.theme} onchange={handleThemeChange}>
					<option value="light">Light</option>
					<option value="dark">Dark</option>
					<option value="system">Match System</option>
				</select>
			</FormField>

			<FormField
				label="Auto-refresh Interval"
				description="How often to automatically refresh the VM list"
			>
				<select bind:value={settings.autoRefreshInterval} onchange={handleAutoRefreshChange}>
					<option value={0}>Disabled</option>
					<option value={30}>30 seconds</option>
					<option value={60}>1 minute</option>
					<option value={300}>5 minutes</option>
				</select>
			</FormField>
		</FormSection>

		<!-- About -->
		<FormSection title="About" description="Version and environment information">
			<div class="info-grid">
				<div class="info-row">
					<span class="info-label">Environment</span>
					<span class="info-value">{settings.environmentName}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Server Version</span>
					<span class="info-value">{settings.serverVersion}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Build Date</span>
					<span class="info-value">{settings.buildDate}</span>
				</div>
			</div>
			<div class="oss-placeholder">
				<p>
					This application uses open-source software. View the full list of dependencies and their
					licenses.
				</p>
				<Button variant="secondary" size="sm" onclick={() => alert('OSS Attributions modal')}>
					View Attributions
				</Button>
			</div>
		</FormSection>

		<!-- Service Diagnostics -->
		<FormSection
			title="Service Diagnostics"
			description="View service health and component status"
			collapsible
			defaultExpanded={false}
		>
			<div class="diagnostics-placeholder">
				<p>
					Service diagnostic information will be displayed here, including inventory refresh status,
					job queue health, and agent deployment status.
				</p>
				<p class="note">
					<strong>Note:</strong> This section will be implemented with real-time service monitoring data.
				</p>
			</div>
		</FormSection>

		<!-- Administration -->
		<FormSection
			title="Administration"
			description="Administrative actions (requires admin permissions)"
		>
			<div class="admin-actions">
				<div class="action-card">
					<div class="action-info">
						<h4 class="action-title">Redeploy Host Scripts</h4>
						<p class="action-description">
							Force redeployment of all PowerShell provisioning scripts to Hyper-V hosts. This
							ensures hosts have the latest agent code.
						</p>
					</div>
					<Button
						variant="danger"
						size="sm"
						onclick={handleRedeployScripts}
						disabled={isSubmitting}
					>
						Redeploy Scripts
					</Button>
				</div>
			</div>
		</FormSection>
	<FormActions>
		<Button variant="secondary" onclick={onClose}>Close</Button>
	</FormActions>
</Modal>

<style>
	.settings-content {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		margin-bottom: 1rem;
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		color: var(--text-primary);
	}

	.checkbox-label input[type='checkbox'] {
		margin: 0;
	}

	.info-grid {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.info-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.625rem 0.75rem;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
	}

	.info-label {
		font-size: 0.875rem;
		color: var(--text-secondary);
		font-weight: 500;
	}

	.info-value {
		font-size: 0.875rem;
		color: var(--text-primary);
		font-family: monospace;
	}

	.diagnostics-placeholder,
	.oss-placeholder {
		padding: 1rem;
		background: var(--bg-tertiary);
		border: 1px dashed var(--border-color);
		border-radius: var(--radius-md);
		font-size: 0.875rem;
		color: var(--text-secondary);
		line-height: 1.6;
	}

	.diagnostics-placeholder p,
	.oss-placeholder p {
		margin: 0 0 0.75rem 0;
	}

	.diagnostics-placeholder p:last-child,
	.oss-placeholder p:last-child {
		margin-bottom: 0;
	}

	.note {
		font-style: italic;
		font-size: 0.8125rem;
	}

	.note strong {
		color: var(--text-primary);
	}

	.admin-actions {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.action-card {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		padding: 1rem;
		background: var(--bg-tertiary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
	}

	.action-info {
		flex: 1;
	}

	.action-title {
		font-size: 0.9375rem;
		font-weight: 600;
		color: var(--text-primary);
		margin: 0 0 0.25rem 0;
	}

	.action-description {
		font-size: 0.8125rem;
		color: var(--text-secondary);
		margin: 0;
		line-height: 1.5;
	}
</style>
