<script lang="ts">
	import Icon from '$lib/components/common/Icon.svelte';

	interface Props {
		title: string;
		message: string;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let { title, message, onConfirm, onCancel }: Props = $props();

	let dialogElement: HTMLDivElement;

	function handleConfirm() {
		onConfirm();
	}

	function handleCancel() {
		onCancel();
	}

	function handleBackdropClick() {
		onCancel();
	}
</script>

<div class="resource-delete-confirm visible">
	<div class="resource-delete-backdrop" onclick={handleBackdropClick}></div>
	<div bind:this={dialogElement} class="resource-delete-dialog" role="dialog" aria-modal="true">
		<div class="resource-delete-header">
			<h3>{title}</h3>
		</div>
		<div class="resource-delete-body">
			<p>{message}</p>
		</div>
		<div class="resource-delete-actions">
			<button type="button" class="btn btn-secondary" onclick={handleCancel}>Cancel</button>
			<button type="button" class="btn btn-danger" onclick={handleConfirm}>Delete</button>
		</div>
	</div>
</div>

<style>
	.resource-delete-confirm {
		position: fixed;
		inset: 0;
		z-index: 2000;
		display: flex;
		align-items: center;
		justify-content: center;
		opacity: 0;
		transition: opacity 0.2s ease;
	}

	.resource-delete-confirm.visible {
		opacity: 1;
	}

	.resource-delete-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		backdrop-filter: blur(4px);
	}

	.resource-delete-dialog {
		position: relative;
		background: var(--bg-primary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
		max-width: 480px;
		width: 90%;
		padding: 1.5rem;
		z-index: 1;
	}

	.resource-delete-header h3 {
		margin: 0;
		font-size: 1.25rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.resource-delete-body {
		margin-top: 1rem;
		color: var(--text-secondary);
		line-height: 1.6;
	}

	.resource-delete-body p {
		margin: 0;
	}

	.resource-delete-actions {
		display: flex;
		gap: 0.75rem;
		justify-content: flex-end;
		margin-top: 1.5rem;
	}

	.btn {
		padding: 0.625rem 1.25rem;
		border-radius: var(--radius-md);
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.15s ease;
		border: none;
	}

	.btn-secondary {
		background: var(--bg-tertiary);
		color: var(--text-primary);
	}

	.btn-secondary:hover {
		background: var(--bg-quaternary);
	}

	.btn-danger {
		background: var(--danger);
		color: white;
	}

	.btn-danger:hover {
		opacity: 0.9;
	}
</style>
