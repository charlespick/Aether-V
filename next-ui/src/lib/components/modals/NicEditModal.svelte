<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import FormField from '$lib/components/forms/FormField.svelte';
	import FormActions from '$lib/components/forms/FormActions.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { toastStore } from '$lib/stores/toastStore';
	import {
		validateRequired,
		combineValidationErrors,
		hasErrors,
		patterns
	} from '$lib/utils/validation';
	import { inventoryStore } from '$lib/stores/inventoryStore';

	interface NicData {
		id: string;
		network: string;
		adapter_name?: string;
	}

	interface Props {
		isOpen: boolean;
		vmId: string;
		vmName: string;
		nic: NicData;
		onClose: () => void;
		onSuccess?: () => void;
	}

	let { isOpen = $bindable(false), vmId, vmName, nic, onClose, onSuccess }: Props = $props();

	// Get VM and Host to populate networks
	let vm = $derived($inventoryStore?.vms?.find(v => v.id === vmId));
	let host = $derived(vm ? $inventoryStore?.hosts?.find(h => h.hostname === vm.host) : undefined);
	let availableNetworks = $derived(host?.resources?.networks || []);
	let selectedNetwork = $derived(availableNetworks.find(n => n.name === formData.network));
	let hasIpSettings = $derived(selectedNetwork?.ip_settings != null);

	// Form state
	let formData = $state({
		network: nic.network,
		adapter_name: nic.adapter_name || ''
	});

	let errors = $state<Record<string, string>>({});

	let isSubmitting = $state(false);
	let isDirty = $derived(
		formData.network !== nic.network ||
		formData.adapter_name !== (nic.adapter_name || '')
	);

	// Validation
	function validate(): boolean {
		const validationErrors = combineValidationErrors([
			...validateRequired(formData, ['network'])
		]);

		// Validate network name pattern
		if (formData.network && !patterns.networkName.test(formData.network)) {
			validationErrors.network = 'Invalid network name format';
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

		// For PATCH, only send changed fields
		const patchBody: Record<string, unknown> = {};
		if (formData.network !== nic.network) {
			patchBody.network = formData.network;
		}
		if (formData.adapter_name !== nic.adapter_name) {
			patchBody.adapter_name = formData.adapter_name;
		}

		if (Object.keys(patchBody).length === 0) {
			toastStore.info('No changes to update');
			return;
		}

		isSubmitting = true;

		try {
			const response = await fetch(`/api/v1/virtualmachines/${encodeURIComponent(vmId)}/networkadapters/${encodeURIComponent(nic.id || '')}`, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(patchBody)
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to update network adapter');
			}

			toastStore.success(`Network adapter updated successfully for ${vmName}`);
			onClose();

			// Refresh VM view after a short delay
			setTimeout(() => {
				onSuccess?.();
			}, 100);
		} catch (error) {
			console.error('Failed to update NIC:', error);
			toastStore.error(
				error instanceof Error ? error.message : 'Failed to update network adapter'
			);
		} finally {
			isSubmitting = false;
		}
	}

	// Reset form when modal opens with new NIC data
	$effect(() => {
		if (isOpen) {
			formData = {
				network: nic.network,
				adapter_name: nic.adapter_name || ''
			};
			errors = {};
		}
	});
</script>

<Modal {isOpen} {onClose} title="Edit Network Adapter" variant="center" width="md">
	<form onsubmit={handleSubmit}>
		<div class="form-content">
			<FormField
				label="Network"
				description="Network to connect this adapter to"
				required
				error={errors.network}
			>
				<select bind:value={formData.network} disabled={isSubmitting}>
					<option value="">Select a network...</option>
					{#each availableNetworks as net}
						<option value={net.name}>{net.name}</option>
					{/each}
				</select>
				{#if hasIpSettings && selectedNetwork?.ip_settings}
					<div class="ip-settings-hint">
						<strong>IP Settings available:</strong>
						{#if selectedNetwork.ip_settings.gateway}
							Gateway: {selectedNetwork.ip_settings.gateway}
						{/if}
						{#if selectedNetwork.ip_settings.dns}
							DNS: {selectedNetwork.ip_settings.dns}
						{/if}
						{#if selectedNetwork.ip_settings.dhcp_available}
							<span class="dhcp-badge">DHCP Available</span>
						{/if}
					</div>
				{/if}
			</FormField>

			<FormField
				label="Adapter Name"
				description="Optional: custom name for this network adapter"
				error={errors.adapter_name}
			>
				<input
					type="text"
					bind:value={formData.adapter_name}
					placeholder="e.g., Network Adapter 2"
					disabled={isSubmitting}
				/>
			</FormField>
		</div>

		<FormActions>
			<Button variant="secondary" onclick={onClose} disabled={isSubmitting}>Cancel</Button>
			<Button type="submit" variant="primary" disabled={isSubmitting || !isDirty}>
				{isSubmitting ? 'Updating...' : 'Update Network Adapter'}
			</Button>
		</FormActions>
	</form>
</Modal>

<style>
	.form-content {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.ip-settings-hint {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background: rgba(34, 197, 94, 0.1);
		border: 1px solid rgba(34, 197, 94, 0.3);
		border-radius: var(--radius-sm);
		font-size: 0.8125rem;
		color: var(--text-secondary);
		line-height: 1.4;
	}

	.ip-settings-hint strong {
		color: rgb(34, 197, 94);
		display: block;
		margin-bottom: 0.25rem;
	}

	.dhcp-badge {
		display: inline-block;
		margin-left: 0.5rem;
		padding: 0.125rem 0.5rem;
		background: rgba(34, 197, 94, 0.2);
		border-radius: var(--radius-sm);
		font-size: 0.75rem;
		font-weight: 500;
		color: rgb(34, 197, 94);
	}
</style>
