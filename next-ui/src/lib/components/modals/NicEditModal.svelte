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

	// Form state
	let formData = $state({
		network: nic.network,
		adapter_name: nic.adapter_name || ''
	});

	let errors = $state<Record<string, string>>({});
	let isSubmitting = $state(false);

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

		isSubmitting = true;

		try {
                        const response = await fetch(`/api/v1/virtualmachines/${encodeURIComponent(vmId)}/networkadapters/${encodeURIComponent(nic.id || '')}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					vm_id: vmId,
					...formData
				})
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
				description="Name of the Hyper-V virtual switch to connect to"
				required
				error={errors.network}
			>
				<input
					type="text"
					bind:value={formData.network}
					placeholder="e.g., Production"
					disabled={isSubmitting}
				/>
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
			<Button type="submit" variant="primary" disabled={isSubmitting}>
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
</style>
