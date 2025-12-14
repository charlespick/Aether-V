<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import FormField from '$lib/components/forms/FormField.svelte';
	import FormActions from '$lib/components/forms/FormActions.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { toastStore } from '$lib/stores/toastStore';
	import {
		validateRequired,
		validateRange,
		combineValidationErrors,
		hasErrors
	} from '$lib/utils/validation';

	interface Props {
		isOpen: boolean;
		vmId: string;
		vmName: string;
		onClose: () => void;
		onSuccess?: () => void;
	}

	let { isOpen = $bindable(false), vmId, vmName, onClose, onSuccess }: Props = $props();

	// Form state
	let formData = $state({
		disk_size_gb: 100,
		disk_type: 'Dynamic' as 'Dynamic' | 'Fixed',
		controller_type: 'SCSI' as 'SCSI' | 'IDE',
		storage_class: ''
	});

	let errors = $state<Record<string, string>>({});
	let isSubmitting = $state(false);

	// Validation
	function validate(): boolean {
		const validationErrors = combineValidationErrors([
			...validateRequired(formData, ['disk_size_gb', 'disk_type', 'controller_type']),
			validateRange(formData, 'disk_size_gb', 1, 65536)
		]);

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
                        const response = await fetch(`/api/v1/virtualmachines/${encodeURIComponent(vmId)}/disks`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					vm_id: vmId,
					...formData
				})
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || 'Failed to create disk');
			}

			toastStore.success(`Disk created successfully for ${vmName}`);
			onClose();

			// Refresh VM view after a short delay
			setTimeout(() => {
				onSuccess?.();
			}, 100);
		} catch (error) {
			console.error('Failed to create disk:', error);
			toastStore.error(error instanceof Error ? error.message : 'Failed to create disk');
		} finally {
			isSubmitting = false;
		}
	}

	// Reset form when modal closes
	$effect(() => {
		if (!isOpen) {
			formData = {
				disk_size_gb: 100,
				disk_type: 'Dynamic',
				controller_type: 'SCSI',
				storage_class: ''
			};
			errors = {};
		}
	});
</script>

<Modal {isOpen} {onClose} title="Create Disk" variant="center" width="md">
	<form onsubmit={handleSubmit}>
		<div class="form-content">
			<FormField
				label="Disk Size (GB)"
				description="Size of the virtual disk in gigabytes"
				required
				error={errors.disk_size_gb}
			>
				<input
					type="number"
					bind:value={formData.disk_size_gb}
					min="1"
					max="65536"
					disabled={isSubmitting}
				/>
			</FormField>

			<FormField
				label="Disk Type"
				description="Dynamic disks grow as needed; fixed disks allocate full size immediately"
				required
				error={errors.disk_type}
			>
				<select bind:value={formData.disk_type} disabled={isSubmitting}>
					<option value="Dynamic">Dynamic</option>
					<option value="Fixed">Fixed</option>
				</select>
			</FormField>

			<FormField
				label="Controller Type"
				description="SCSI is recommended for most scenarios"
				required
				error={errors.controller_type}
			>
				<select bind:value={formData.controller_type} disabled={isSubmitting}>
					<option value="SCSI">SCSI</option>
					<option value="IDE">IDE</option>
				</select>
			</FormField>

			<FormField
				label="Storage Class"
				description="Optional: storage tier or class identifier (deprecated in v0.5.0)"
				error={errors.storage_class}
			>
				<input
					type="text"
					bind:value={formData.storage_class}
					placeholder="e.g., SSD-Tier1"
					disabled={isSubmitting}
				/>
			</FormField>

			<div class="field-note">
				<strong>Note:</strong> The disk will be created and attached to {vmName}.
			</div>
		</div>

		<FormActions>
			<Button variant="secondary" onclick={onClose} disabled={isSubmitting}>Cancel</Button>
			<Button type="submit" variant="primary" disabled={isSubmitting}>
				{isSubmitting ? 'Creating...' : 'Create Disk'}
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

	.field-note {
		padding: 0.75rem;
		background: rgba(74, 158, 255, 0.1);
		border: 1px solid rgba(74, 158, 255, 0.3);
		border-radius: var(--radius-md);
		font-size: 0.8125rem;
		color: var(--text-secondary);
		line-height: 1.4;
	}

	.field-note strong {
		color: var(--accent-primary);
	}
</style>
