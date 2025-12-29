<script lang="ts">
	import { toastStore, type Toast } from '$lib/stores/toastStore';
	import Icon from '$lib/components/common/Icon.svelte';

	const MAX_VISIBLE = 3;
	let containerRef: HTMLDivElement;
	let scrollPosition = 0;

	// Handle scroll to reveal overflow toasts
	function handleWheel(event: WheelEvent) {
		const container = containerRef;
		if (!container) return;

		const maxScroll = Math.max(0, container.scrollHeight - container.clientHeight);
		scrollPosition = Math.max(0, Math.min(maxScroll, scrollPosition + event.deltaY));
		container.scrollTop = scrollPosition;
		event.preventDefault();
	}
</script>

<div 
	class="toast-container" 
	bind:this={containerRef}
	onwheel={handleWheel}
>
	{#each $toastStore as toast, index (toast.id)}
		<div 
			class="toast" 
			class:overflow={index >= MAX_VISIBLE}
			data-type={toast.type}
		>
			<div class="toast-icon">
				{#if toast.icon}
					<!-- Use cached Material Icons -->
					<Icon name={toast.icon} size={20} />
				{:else if toast.type === 'success'}
					<Icon name="check_circle" size={20} />
				{:else if toast.type === 'error'}
					<Icon name="error" size={20} />
				{:else if toast.type === 'warning'}
					<Icon name="warning" size={20} />
				{:else}
					<Icon name="info" size={20} />
				{/if}
			</div>
			<div class="toast-content">
				{#if toast.title}
					<div class="toast-title">{toast.title}</div>
				{/if}
				<div class="toast-message">
					{toast.message}
					{#if toast.countdown && toast.countdown > 0}
						<span class="toast-countdown">({toast.countdown}s)</span>
					{/if}
				</div>
				{#if toast.action}
					<button class="toast-action" onclick={toast.action.callback}>
						{toast.action.label}
					</button>
				{/if}
			</div>
			{#if toast.dismissible !== false}
				<button class="toast-close" onclick={() => toastStore.remove(toast.id)} aria-label="Close">
					<Icon name="close" size={16} />
				</button>
			{/if}
		</div>
	{/each}
</div>

<style>
	.toast-container {
		position: fixed;
		bottom: 1rem;
		right: 1rem;
		z-index: 9999;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		pointer-events: none;
		max-height: calc(100vh - 2rem);
		overflow-y: auto;
		overflow-x: visible;
		padding-right: 0.25rem; /* Space for scrollbar if needed */
	}

	/* Hide scrollbar but keep functionality */
	.toast-container::-webkit-scrollbar {
		width: 0;
		background: transparent;
	}

	.toast {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 1rem;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-lg);
		min-width: 300px;
		max-width: 400px;
		pointer-events: auto;
		animation: slideIn 0.3s ease;
		transition: all 0.3s ease;
	}

	/* Overflow toasts show only top edge (peek) */
	.toast.overflow {
		max-height: 20px;
		overflow: hidden;
		opacity: 0.6;
		cursor: pointer;
		padding: 0.5rem 1rem;
	}

	.toast.overflow:hover {
		opacity: 0.8;
	}

	@keyframes slideIn {
		from {
			transform: translateX(100%);
			opacity: 0;
		}
		to {
			transform: translateX(0);
			opacity: 1;
		}
	}

	.toast[data-type="success"] {
		border-left: 3px solid var(--success);
	}

	.toast[data-type="error"] {
		border-left: 3px solid var(--error);
	}

	.toast[data-type="warning"] {
		border-left: 3px solid var(--warning);
	}

	.toast[data-type="info"] {
		border-left: 3px solid var(--info);
	}

	.toast-icon {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		margin-top: 0.125rem; /* Align with title */
	}

	.toast[data-type="success"] .toast-icon {
		color: var(--success);
	}

	.toast[data-type="error"] .toast-icon {
		color: var(--error);
	}

	.toast[data-type="warning"] .toast-icon {
		color: var(--warning);
	}

	.toast[data-type="info"] .toast-icon {
		color: var(--info);
	}

	.toast-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		min-width: 0; /* Allow text truncation */
	}

	.toast-title {
		color: var(--text-primary);
		font-size: 0.875rem;
		font-weight: 600;
		line-height: 1.3;
	}

	.toast-message {
		color: var(--text-secondary);
		font-size: 0.8125rem;
		line-height: 1.4;
	}

	.toast-countdown {
		color: var(--text-tertiary);
		font-weight: 500;
		margin-left: 0.25rem;
	}

	.toast-action {
		align-self: flex-start;
		margin-top: 0.5rem;
		padding: 0.375rem 0.875rem;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--accent-color);
		background: transparent;
		border: 1px solid var(--accent-color);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition-fast);
	}

	.toast-action:hover {
		background: var(--accent-color);
		color: white;
	}

	.toast-close {
		flex-shrink: 0;
		padding: 0.25rem;
		color: var(--text-secondary);
		border-radius: var(--radius-sm);
		transition: all var(--transition-fast);
		background: transparent;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		align-self: flex-start;
		margin-top: 0.125rem; /* Align with title */
	}

	.toast-close:hover {
		color: var(--text-primary);
		background-color: var(--bg-hover);
	}
</style>
