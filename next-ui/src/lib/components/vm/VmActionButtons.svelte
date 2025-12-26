<script lang="ts">
	import Icon from '$lib/components/common/Icon.svelte';
	import { getActionAvailability } from '$lib/utils/vm';
	import type { VM } from '$lib/stores/inventoryStore';

	interface Props {
		vm: VM;
		actionInProgress?: boolean;
		onAction: (action: string) => void;
	}

	let { vm, actionInProgress = false, onAction }: Props = $props();

	const availability = $derived(getActionAvailability(vm.state, actionInProgress));

	interface ActionDef {
		action: string;
		iconName: string;
		tooltip: string;
		aria: string;
	}

	const actions: ActionDef[] = [
		{ action: 'edit', iconName: 'edit', tooltip: 'Edit VM', aria: 'Edit virtual machine' },
		{ action: 'start', iconName: 'play_circle', tooltip: 'Start', aria: 'Start virtual machine' },
		{
			action: 'shutdown',
			iconName: 'power_settings_new',
			tooltip: 'Shut Down',
			aria: 'Shut down virtual machine'
		},
		{
			action: 'stop',
			iconName: 'stop_circle',
			tooltip: 'Turn Off',
			aria: 'Stop (Turn Off) virtual machine'
		},
		{ action: 'reset', iconName: 'autorenew', tooltip: 'Reset', aria: 'Reset virtual machine' },
		{ action: 'delete', iconName: 'delete', tooltip: 'Delete', aria: 'Delete virtual machine' }
	];

	function handleClick(action: string, allowed: boolean) {
		if (!allowed || actionInProgress) return;
		onAction(action);
	}
</script>

<div class="vm-action-bar" role="toolbar" aria-label="Virtual machine controls">
	{#each actions as { action, iconName, tooltip, aria }}
		{@const allowed = availability[action as keyof typeof availability]}
		<button
			type="button"
			class="vm-action-btn"
			class:disabled={!allowed}
			data-action={action}
			data-tooltip={tooltip}
			aria-label={aria}
			disabled={!allowed}
			onclick={() => handleClick(action, allowed)}
		>
			<Icon name={iconName} className="vm-action-symbol" size={22} />
		</button>
	{/each}
</div>

<style>
	.vm-action-bar {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
	}

	.vm-action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
		background: var(--bg-secondary);
		color: var(--text-primary);
		cursor: pointer;
		transition: all 0.2s ease;
		position: relative;
	}

	.vm-action-btn:hover:not(:disabled) {
		background: var(--bg-tertiary);
		border-color: var(--border-color-hover);
		transform: translateY(-1px);
	}

	.vm-action-btn:active:not(:disabled) {
		transform: translateY(0);
	}

	.vm-action-btn:disabled,
	.vm-action-btn.disabled {
		opacity: 0.4;
		cursor: not-allowed;
		pointer-events: none;
	}

	.vm-action-btn[data-action='delete'] {
		color: var(--danger);
	}

	.vm-action-btn[data-action='delete']:hover:not(:disabled) {
		background: var(--danger);
		color: white;
		border-color: var(--danger);
	}

	/* Tooltip on hover */
	.vm-action-btn::after {
		content: attr(data-tooltip);
		position: absolute;
		bottom: -2rem;
		left: 50%;
		transform: translateX(-50%);
		padding: 0.25rem 0.5rem;
		background: var(--bg-tooltip, rgba(0, 0, 0, 0.9));
		color: white;
		border-radius: var(--radius-sm);
		font-size: 0.75rem;
		white-space: nowrap;
		opacity: 0;
		pointer-events: none;
		transition: opacity 0.2s ease;
		z-index: 1000;
	}

	.vm-action-btn:hover::after:not(:disabled) {
		opacity: 1;
	}
</style>
