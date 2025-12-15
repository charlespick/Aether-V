<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import FormField from '$lib/components/forms/FormField.svelte';
	import FormActions from '$lib/components/forms/FormActions.svelte';
	import { toastStore } from '$lib/stores/toastStore';
	import {
		validateRequired,
		validateRange,
		combineValidationErrors,
		hasErrors
	} from '$lib/utils/validation';
	import type { VM } from '$lib/stores/inventoryStore';

	interface Props {
		isOpen: boolean;
		vm: VM;
		onClose: () => void;
		onSuccess?: () => void;
	}

	let { isOpen = $bindable(false), vm, onClose, onSuccess }: Props = $props();

	let activeTab = $state('hardware');
	const tabs = [
		{ id: 'hardware', label: 'Hardware' },
		{ id: 'security', label: 'Security' },
		{ id: 'host', label: 'Host Integration' }
	];

	// Form state
	let formData = $state({
		// Hardware
		cpu_cores: vm.cpu_cores || 1,
		memory_startup_gb: vm.memory_startup_gb || vm.memory_gb || 1,
		memory_min_gb: vm.memory_min_gb || 0.5,
		memory_max_gb: vm.memory_max_gb || 2,
		dynamic_memory_enabled: vm.dynamic_memory_enabled || false,
		memory_prcnt_buffer: vm.dynamic_memory_buffer || 20,
		
		// Security
		secure_boot: vm.secure_boot_template || 'Microsoft Windows',
		tpm_enabled: vm.trusted_platform_module_enabled || false,
		
		// Host Actions
		host_recovery_action: vm.host_recovery_action || 'none',
		host_stop_action: vm.host_stop_action || 'save',
		
		// Integration Services
		integration_services_shutdown: vm.integration_services_shutdown ?? true,
		integration_services_time: vm.integration_services_time ?? true,
		integration_services_data_exchange: vm.integration_services_data_exchange ?? true,
		integration_services_heartbeat: vm.integration_services_heartbeat ?? true,
		integration_services_vss_backup: vm.integration_services_vss_backup ?? true,
		integration_services_guest_services: vm.integration_services_guest_services ?? false
	});

	let errors = $state<Record<string, string>>({});

	let isSubmitting = $state(false);
	let isDirty = $derived(
		formData.cpu_cores !== (vm.cpu_cores || 1) ||
		formData.memory_startup_gb !== (vm.memory_startup_gb || vm.memory_gb || 1) ||
		formData.memory_min_gb !== (vm.memory_min_gb || 0.5) ||
		formData.memory_max_gb !== (vm.memory_max_gb || 2) ||
		formData.dynamic_memory_enabled !== (vm.dynamic_memory_enabled || false) ||
		formData.memory_prcnt_buffer !== (vm.dynamic_memory_buffer || 20) ||
		formData.secure_boot !== (vm.secure_boot_template || 'Microsoft Windows') ||
		formData.tpm_enabled !== (vm.trusted_platform_module_enabled || false) ||
		formData.host_recovery_action !== (vm.host_recovery_action || 'none') ||
		formData.host_stop_action !== (vm.host_stop_action || 'save') ||
		formData.integration_services_shutdown !== (vm.integration_services_shutdown ?? true) ||
		formData.integration_services_time !== (vm.integration_services_time ?? true) ||
		formData.integration_services_data_exchange !== (vm.integration_services_data_exchange ?? true) ||
		formData.integration_services_heartbeat !== (vm.integration_services_heartbeat ?? true) ||
		formData.integration_services_vss_backup !== (vm.integration_services_vss_backup ?? true) ||
		formData.integration_services_guest_services !== (vm.integration_services_guest_services ?? false)
	);

	// Update form data when VM changes or modal opens
	$effect(() => {
		if (isOpen && vm) {
			formData = {
				cpu_cores: vm.cpu_cores || 1,
				memory_startup_gb: vm.memory_startup_gb || vm.memory_gb || 1,
				memory_min_gb: vm.memory_min_gb || 0.5,
				memory_max_gb: vm.memory_max_gb || 2,
				dynamic_memory_enabled: vm.dynamic_memory_enabled || false,
				memory_prcnt_buffer: vm.dynamic_memory_buffer || 20,
				
				secure_boot: vm.secure_boot_template || 'Microsoft Windows',
				tpm_enabled: vm.trusted_platform_module_enabled || false,
				
				host_recovery_action: vm.host_recovery_action || 'none',
				host_stop_action: vm.host_stop_action || 'save',
				
				integration_services_shutdown: vm.integration_services_shutdown ?? true,
				integration_services_time: vm.integration_services_time ?? true,
				integration_services_data_exchange: vm.integration_services_data_exchange ?? true,
				integration_services_heartbeat: vm.integration_services_heartbeat ?? true,
				integration_services_vss_backup: vm.integration_services_vss_backup ?? true,
				integration_services_guest_services: vm.integration_services_guest_services ?? false
			};
		}
	});

	// Validation
	function validate(): boolean {
		const validationErrors = combineValidationErrors([
			...validateRequired(formData, ['cpu_cores', 'memory_startup_gb']),
			validateRange(formData, 'cpu_cores', 1, 64),
			validateRange(formData, 'memory_startup_gb', 0.5, 1024)
		]);

		if (formData.dynamic_memory_enabled) {
			if (formData.memory_min_gb > formData.memory_startup_gb) {
				validationErrors.memory_min_gb = 'Minimum memory cannot be greater than startup memory';
			}
			if (formData.memory_max_gb < formData.memory_startup_gb) {
				validationErrors.memory_max_gb = 'Maximum memory cannot be less than startup memory';
			}
			validateRange(formData, 'memory_prcnt_buffer', 5, 100);
		}

		errors = validationErrors;
		return !hasErrors(validationErrors);
	}

	// Handle form submission
	async function handleSubmit(e: Event) {
		e.preventDefault();

		if (!validate()) {
			toastStore.error('Please fix the validation errors');
			return;
		}

		// Only send changed fields (PATCH semantics)
		const patchBody: Record<string, unknown> = {};
		if (formData.cpu_cores !== (vm.cpu_cores || 1)) patchBody.cpu_cores = formData.cpu_cores;
		if (formData.memory_startup_gb !== (vm.memory_startup_gb || vm.memory_gb || 1)) patchBody.memory_startup_gb = formData.memory_startup_gb;
		if (formData.memory_min_gb !== (vm.memory_min_gb || 0.5)) patchBody.memory_min_gb = formData.memory_min_gb;
		if (formData.memory_max_gb !== (vm.memory_max_gb || 2)) patchBody.memory_max_gb = formData.memory_max_gb;
		if (formData.dynamic_memory_enabled !== (vm.dynamic_memory_enabled || false)) patchBody.dynamic_memory_enabled = formData.dynamic_memory_enabled;
		if (formData.memory_prcnt_buffer !== (vm.dynamic_memory_buffer || 20)) patchBody.memory_prcnt_buffer = formData.memory_prcnt_buffer;
		if (formData.secure_boot !== (vm.secure_boot_template || 'Microsoft Windows')) patchBody.secure_boot = formData.secure_boot;
		if (formData.tpm_enabled !== (vm.trusted_platform_module_enabled || false)) patchBody.tpm_enabled = formData.tpm_enabled;
		if (formData.host_recovery_action !== (vm.host_recovery_action || 'none')) patchBody.host_recovery_action = formData.host_recovery_action;
		if (formData.host_stop_action !== (vm.host_stop_action || 'save')) patchBody.host_stop_action = formData.host_stop_action;
		if (formData.integration_services_shutdown !== (vm.integration_services_shutdown ?? true)) patchBody.integration_services_shutdown = formData.integration_services_shutdown;
		if (formData.integration_services_time !== (vm.integration_services_time ?? true)) patchBody.integration_services_time = formData.integration_services_time;
		if (formData.integration_services_data_exchange !== (vm.integration_services_data_exchange ?? true)) patchBody.integration_services_data_exchange = formData.integration_services_data_exchange;
		if (formData.integration_services_heartbeat !== (vm.integration_services_heartbeat ?? true)) patchBody.integration_services_heartbeat = formData.integration_services_heartbeat;
		if (formData.integration_services_vss_backup !== (vm.integration_services_vss_backup ?? true)) patchBody.integration_services_vss_backup = formData.integration_services_vss_backup;
		if (formData.integration_services_guest_services !== (vm.integration_services_guest_services ?? false)) patchBody.integration_services_guest_services = formData.integration_services_guest_services;

		if (Object.keys(patchBody).length === 0) {
			toastStore.info('No changes to update');
			return;
		}

		isSubmitting = true;

		try {
			const response = await fetch(`/api/v1/virtualmachines/${encodeURIComponent(vm.id)}`, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(patchBody)
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to update VM');
			}

			toastStore.success(`VM ${vm.name} updated successfully`);
			onClose();

			// Refresh VM view after a short delay
			setTimeout(() => {
				onSuccess?.();
			}, 100);
		} catch (error) {
			console.error('Failed to update VM:', error);
			toastStore.error(error instanceof Error ? error.message : 'Failed to update VM');
		} finally {
			isSubmitting = false;
		}
	}
</script>

<Modal title="Edit Virtual Machine" bind:isOpen {onClose} width="lg">
	<div class="flex flex-col h-full">
		<!-- Tabs -->
		<div class="flex border-b border-border mb-4 gap-1">
			{#each tabs as tab}
				<button
					class="px-4 py-2 text-sm font-medium border-b-2 transition-colors hover:bg-surface-2 rounded-t-md {activeTab === tab.id
						? 'border-primary text-primary bg-surface-2'
						: 'border-transparent text-text-secondary hover:text-text-primary'}"
					onclick={() => (activeTab = tab.id)}
				>
					{tab.label}
				</button>
			{/each}
		</div>

		<form onsubmit={handleSubmit} class="space-y-4 flex-1 overflow-y-auto p-1">
			{#if activeTab === 'hardware'}
				<div class="space-y-4">
					<FormField
						label="CPU Cores"
						id="cpu_cores"
						error={errors.cpu_cores}
						required
					>
						<input
							type="number"
							id="cpu_cores"
							bind:value={formData.cpu_cores}
							min="1"
							max="64"
							class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						/>
					</FormField>

					<div class="border-t border-border pt-4 mt-4">
						<h3 class="text-sm font-medium mb-3">Memory Configuration</h3>
						
						<FormField
							label="Startup Memory (GB)"
							id="memory_startup_gb"
							error={errors.memory_startup_gb}
							required
						>
							<input
								type="number"
								id="memory_startup_gb"
								step="0.1"
								bind:value={formData.memory_startup_gb}
								min="0.5"
								class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
							/>
						</FormField>

						<div class="flex items-center gap-2 mb-4">
							<input
								type="checkbox"
								id="dynamic_memory"
								bind:checked={formData.dynamic_memory_enabled}
								class="rounded border-border text-primary focus:ring-primary"
							/>
							<label for="dynamic_memory" class="text-sm font-medium text-text-primary">
								Enable Dynamic Memory
							</label>
						</div>

						{#if formData.dynamic_memory_enabled}
							<div class="grid grid-cols-2 gap-4">
								<FormField
									label="Minimum Memory (GB)"
									id="memory_min_gb"
									error={errors.memory_min_gb}
								>
									<input
										type="number"
										id="memory_min_gb"
										step="0.1"
										bind:value={formData.memory_min_gb}
										min="0.5"
										class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
									/>
								</FormField>
								<FormField
									label="Maximum Memory (GB)"
									id="memory_max_gb"
									error={errors.memory_max_gb}
								>
									<input
										type="number"
										id="memory_max_gb"
										step="0.1"
										bind:value={formData.memory_max_gb}
										min="0.5"
										class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
									/>
								</FormField>
								<FormField
									label="Memory Buffer (%)"
									id="memory_prcnt_buffer"
									error={errors.memory_prcnt_buffer}
								>
									<input
										type="number"
										id="memory_prcnt_buffer"
										bind:value={formData.memory_prcnt_buffer}
										min="5"
										max="100"
										class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
									/>
								</FormField>
							</div>
						{/if}
					</div>
				</div>
			{:else if activeTab === 'security'}
				<FormField
					label="Secure Boot Template"
					id="secure_boot"
					error={errors.secure_boot}
				>
					<select
						bind:value={formData.secure_boot}
						class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
					>
						<option value="Microsoft Windows">Microsoft Windows</option>
						<option value="Microsoft UEFI Certificate Authority">Microsoft UEFI Certificate Authority</option>
						<option value="Open Source Shielded VM">Open Source Shielded VM</option>
						<option value="Disabled">Disabled</option>
					</select>
				</FormField>

				<div class="flex items-center gap-2">
					<input
						type="checkbox"
						id="tpm_enabled"
						bind:checked={formData.tpm_enabled}
						class="rounded border-border text-primary focus:ring-primary"
					/>
					<label for="tpm_enabled" class="text-sm font-medium text-text-primary">
						Enable Trusted Platform Module (TPM)
					</label>
				</div>
			{:else if activeTab === 'host'}
				<div class="grid grid-cols-2 gap-4">
					<FormField
						label="Automatic Stop Action"
						id="host_stop_action"
						error={errors.host_stop_action}
					>
						<select
							bind:value={formData.host_stop_action}
							class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						>
							<option value="save">Save State</option>
							<option value="stop">Turn Off</option>
							<option value="shut-down">Shut Down Guest OS</option>
						</select>
					</FormField>

					<FormField
						label="Automatic Start Action"
						id="host_recovery_action"
						error={errors.host_recovery_action}
					>
						<select
							bind:value={formData.host_recovery_action}
							class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
						>
							<option value="none">Nothing</option>
							<option value="resume">Automatically Start if Running</option>
							<option value="always-start">Always Start</option>
						</select>
					</FormField>
				</div>

				<div class="border-t border-border pt-4 mt-4">
					<h3 class="text-sm font-medium mb-3">Integration Services</h3>
					<div class="space-y-2">
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_shutdown" bind:checked={formData.integration_services_shutdown} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_shutdown" class="text-sm text-text-primary">Operating System Shutdown</label>
						</div>
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_time" bind:checked={formData.integration_services_time} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_time" class="text-sm text-text-primary">Time Synchronization</label>
						</div>
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_data" bind:checked={formData.integration_services_data_exchange} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_data" class="text-sm text-text-primary">Data Exchange</label>
						</div>
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_heartbeat" bind:checked={formData.integration_services_heartbeat} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_heartbeat" class="text-sm text-text-primary">Heartbeat</label>
						</div>
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_backup" bind:checked={formData.integration_services_vss_backup} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_backup" class="text-sm text-text-primary">Backup (volume shadow copy)</label>
						</div>
						<div class="flex items-center gap-2">
							<input type="checkbox" id="is_guest" bind:checked={formData.integration_services_guest_services} class="rounded border-border text-primary focus:ring-primary" />
							<label for="is_guest" class="text-sm text-text-primary">Guest Services</label>
						</div>
					</div>
				</div>
			{/if}

			<FormActions
				{isSubmitting}
				submitLabel="Save Changes"
				onCancel={onClose}
				submitDisabled={!isDirty}
			/>
		</form>
	</div>
</Modal>
