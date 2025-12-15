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

	// Form state
	let formData = $state({
		cpu_cores: vm.cpu_cores || 1,
		memory_startup_gb: vm.memory_startup_gb || vm.memory_gb || 1,
		memory_min_gb: vm.memory_min_gb || 0.5,
		memory_max_gb: vm.memory_max_gb || 2,
		dynamic_memory_enabled: vm.dynamic_memory_enabled || false
	});

	let errors = $state<Record<string, string>>({});
	let isSubmitting = $state(false);

	// Update form data when VM changes or modal opens
	$effect(() => {
		if (isOpen && vm) {
			formData = {
				cpu_cores: vm.cpu_cores || 1,
				memory_startup_gb: vm.memory_startup_gb || vm.memory_gb || 1,
				memory_min_gb: vm.memory_min_gb || 0.5,
				memory_max_gb: vm.memory_max_gb || 2,
				dynamic_memory_enabled: vm.dynamic_memory_enabled || false
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
			const response = await fetch(`/api/v1/virtualmachines/${encodeURIComponent(vm.id)}`, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					vm_id: vm.id,
					vm_name: vm.name,
					...formData
				})
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

<Modal title="Edit Virtual Machine" bind:isOpen {onClose}>
	<form onsubmit={handleSubmit} class="space-y-4">
		<FormField
			label="CPU Cores"
			id="cpu_cores"
			type="number"
			bind:value={formData.cpu_cores}
			error={errors.cpu_cores}
			min="1"
			max="64"
			required
		/>

		<div class="border-t border-border pt-4 mt-4">
			<h3 class="text-sm font-medium mb-3">Memory Configuration</h3>
			
			<FormField
				label="Startup Memory (GB)"
				id="memory_startup_gb"
				type="number"
				step="0.1"
				bind:value={formData.memory_startup_gb}
				error={errors.memory_startup_gb}
				min="0.5"
				required
			/>

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
						type="number"
						step="0.1"
						bind:value={formData.memory_min_gb}
						error={errors.memory_min_gb}
						min="0.5"
					/>
					<FormField
						label="Maximum Memory (GB)"
						id="memory_max_gb"
						type="number"
						step="0.1"
						bind:value={formData.memory_max_gb}
						error={errors.memory_max_gb}
						min="0.5"
					/>
				</div>
			{/if}
		</div>

		<FormActions
			{isSubmitting}
			submitLabel="Save Changes"
			onCancel={onClose}
		/>
	</form>
</Modal>
