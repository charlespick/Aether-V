<script lang="ts">
	import Icon from '../common/Icon.svelte';
	
	interface SlideOverProps {
		isOpen: boolean;
		onClose: () => void;
		title?: string;
		children?: any;
	}

	let {
		isOpen = false,
		onClose,
		title = 'Details',
		children
	}: SlideOverProps = $props();

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			onClose();
		}
	}
</script>

{#if isOpen}
	<div class="overlay" onclick={handleBackdropClick}>
		<div class="slideover">
			<div class="slideover-header">
				<h2>{title}</h2>
				<button class="close-btn" onclick={onClose}>
					<Icon name="close" size={24} />
				</button>
			</div>
			<div class="slideover-content">
				{@render children?.()}
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background-color: rgba(0, 0, 0, 0.6);
		z-index: 1000;
		display: flex;
		justify-content: flex-end;
		animation: fadeIn 0.2s ease;
	}

	@keyframes fadeIn {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	.slideover {
		width: 100%;
		max-width: 600px;
		background-color: var(--bg-secondary);
		box-shadow: var(--shadow-lg);
		display: flex;
		flex-direction: column;
		animation: slideIn 0.3s ease;
	}

	@keyframes slideIn {
		from { transform: translateX(100%); }
		to { transform: translateX(0); }
	}

	.slideover-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1.5rem;
		border-bottom: 1px solid var(--border-color);
	}

	.slideover-header h2 {
		margin: 0;
		font-size: 1.25rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.close-btn {
		padding: 0.5rem;
		color: var(--text-secondary);
		border-radius: var(--radius-sm);
		transition: all var(--transition-fast);
	}

	.close-btn:hover {
		color: var(--text-primary);
		background-color: var(--bg-hover);
	}

	.slideover-content {
		flex: 1;
		padding: 1.5rem;
		overflow-y: auto;
	}
</style>
