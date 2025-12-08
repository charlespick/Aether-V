<script lang="ts">
	import { toastStore } from '$lib/stores/toastStore';
</script>

<div class="toast-container">
	{#each $toastStore as toast (toast.id)}
		<div class="toast" data-type={toast.type}>
			<div class="toast-icon">
				{#if toast.type === 'success'}
					<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<path d="M20 6 9 17l-5-5"></path>
					</svg>
				{:else if toast.type === 'error'}
					<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<circle cx="12" cy="12" r="10"></circle>
						<line x1="15" y1="9" x2="9" y2="15"></line>
						<line x1="9" y1="9" x2="15" y2="15"></line>
					</svg>
				{:else if toast.type === 'warning'}
					<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>
						<line x1="12" y1="9" x2="12" y2="13"></line>
						<line x1="12" y1="17" x2="12.01" y2="17"></line>
					</svg>
				{:else}
					<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
						<circle cx="12" cy="12" r="10"></circle>
						<line x1="12" y1="16" x2="12" y2="12"></line>
						<line x1="12" y1="8" x2="12.01" y2="8"></line>
					</svg>
				{/if}
			</div>
			<div class="toast-message">{toast.message}</div>
			<button class="toast-close" onclick={() => toastStore.removeToast(toast.id)}>
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor">
					<line x1="18" y1="6" x2="6" y2="18"></line>
					<line x1="6" y1="6" x2="18" y2="18"></line>
				</svg>
			</button>
		</div>
	{/each}
</div>

<style>
	.toast-container {
		position: fixed;
		top: 1rem;
		right: 1rem;
		z-index: 9999;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		pointer-events: none;
	}

	.toast {
		display: flex;
		align-items: center;
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

	.toast-message {
		flex: 1;
		color: var(--text-primary);
		font-size: 0.875rem;
	}

	.toast-close {
		flex-shrink: 0;
		padding: 0.25rem;
		color: var(--text-secondary);
		border-radius: var(--radius-sm);
		transition: all var(--transition-fast);
	}

	.toast-close:hover {
		color: var(--text-primary);
		background-color: var(--bg-hover);
	}
</style>
