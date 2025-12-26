<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { clickOutside } from '$lib/actions/clickOutside';

	interface Props {
		isOpen: boolean;
		onClose: () => void;
		title?: string;
		variant?: 'slideOver' | 'center';
		width?: 'sm' | 'md' | 'lg' | 'xl';
		closeOnBackdrop?: boolean;
		closeOnEscape?: boolean;
		children?: any;
	}

	let {
		isOpen = $bindable(false),
		onClose,
		title,
		variant = 'center',
		width = 'md',
		closeOnBackdrop = true,
		closeOnEscape = true,
		children
	}: Props = $props();

	let modalElement: HTMLDivElement;
	let previousActiveElement: Element | null = null;
	let isClosing = $state(false);
	let shouldRender = $state(false);

	// Width mapping
	const widthClasses = {
		sm: 'max-w-md',
		md: 'max-w-2xl',
		lg: 'max-w-4xl',
		xl: 'max-w-6xl'
	};

	// Handle escape key
	function handleKeydown(e: KeyboardEvent) {
		if (closeOnEscape && e.key === 'Escape' && isOpen && !isClosing) {
			e.preventDefault();
			handleClose();
		}
	}

	// Handle backdrop click
	function handleBackdropClick(e: MouseEvent) {
		if (closeOnBackdrop && e.target === e.currentTarget && !isClosing) {
			handleClose();
		}
	}

	// Handle close with animation
	function handleClose() {
		isClosing = true;
		// Wait for animation to complete before actually closing
		setTimeout(() => {
			isClosing = false;
			shouldRender = false;
			onClose();
		}, 300); // Match animation duration
	}

	// Handle opening/closing
	$effect(() => {
		if (isOpen) {
			shouldRender = true;
			isClosing = false;
		} else if (shouldRender && !isClosing) {
			// User closed via external state change (not our handleClose)
			handleClose();
		}
	});

	// Lock/unlock body scroll
	$effect(() => {
		if (shouldRender && !isClosing) {
			previousActiveElement = document.activeElement;
			document.body.style.overflow = 'hidden';
			// Focus trap: focus first focusable element in modal
			setTimeout(() => {
				const focusable = modalElement?.querySelector<HTMLElement>(
					'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
				);
				focusable?.focus();
			}, 100);
		} else if (!shouldRender) {
			document.body.style.overflow = '';
			// Restore focus
			if (previousActiveElement instanceof HTMLElement) {
				previousActiveElement.focus();
			}
		}
	});

	onMount(() => {
		document.addEventListener('keydown', handleKeydown);
	});

	onDestroy(() => {
		document.removeEventListener('keydown', handleKeydown);
		document.body.style.overflow = '';
	});
</script>

{#if shouldRender}
	<div class="modal-container" class:slide-over={variant === 'slideOver'} class:closing={isClosing}>
		<!-- Backdrop -->
		<div
			class="modal-backdrop"
			class:blur={variant === 'center'}
			onclick={handleBackdropClick}
		></div>

		<!-- Modal Panel -->
		<div
			bind:this={modalElement}
			class="modal-panel"
			class:center={variant === 'center'}
			class:slide-over-panel={variant === 'slideOver'}
			class:sm={width === 'sm'}
			class:md={width === 'md'}
			class:lg={width === 'lg'}
			class:xl={width === 'xl'}
			use:clickOutside={() => closeOnBackdrop && !isClosing && handleClose()}
		>
			{#if title}
				<div class="modal-header">
					<h2 class="modal-title">{title}</h2>
					<button class="modal-close" onclick={handleClose} aria-label="Close">
						<svg
							width="20"
							height="20"
							viewBox="0 0 20 20"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
						>
							<path d="M5 5L15 15M15 5L5 15" />
						</svg>
					</button>
				</div>
			{/if}

			<div class="modal-content">
				{@render children?.()}
			</div>
		</div>
	</div>
{/if}

<style>
	.modal-container {
		position: fixed;
		inset: 0;
		z-index: 1000;
		display: flex;
		align-items: center;
		justify-content: center;
		animation: fade-in 0.2s ease;
	}

	.modal-container.slide-over {
		justify-content: flex-end;
	}

	.modal-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		cursor: pointer;
	}

	.modal-backdrop.blur {
		backdrop-filter: blur(2px);
	}

	.modal-panel {
		position: relative;
		background: var(--bg-secondary);
		display: flex;
		flex-direction: column;
		max-height: 90vh;
		overflow: hidden;
		box-shadow: var(--shadow-lg);
	}

	.modal-panel.center {
		border-radius: var(--radius-lg);
		margin: 1rem;
		animation: scale-in 0.2s ease;
	}

	.modal-panel.slide-over-panel {
		width: 100%;
		max-width: 600px;
		height: 100vh;
		max-height: 100vh;
		border-radius: 0;
		animation: slide-in 0.3s ease;
	}

	/* Width classes for center modals */
	.modal-panel.center.sm {
		width: 100%;
		max-width: 28rem;
	}

	.modal-panel.center.md {
		width: 100%;
		max-width: 42rem;
	}

	.modal-panel.center.lg {
		width: 100%;
		max-width: 56rem;
	}

	.modal-panel.center.xl {
		width: 100%;
		max-width: 72rem;
	}

	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1.5rem;
		border-bottom: 1px solid var(--border-color);
		flex-shrink: 0;
	}

	.modal-title {
		font-size: 1.25rem;
		font-weight: 600;
		color: var(--text-primary);
		margin: 0;
	}

	.modal-close {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		border: none;
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		border-radius: var(--radius-md);
		transition: all 0.2s;
	}

	.modal-close:hover {
		background: var(--bg-hover);
		color: var(--text-primary);
	}

	.modal-content {
		flex: 1;
		overflow-y: auto;
		padding: 1.5rem;
	}

	/* Animations */
	@keyframes fade-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes fade-out {
		from {
			opacity: 1;
		}
		to {
			opacity: 0;
		}
	}

	@keyframes scale-in {
		from {
			opacity: 0;
			transform: scale(0.95);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}

	@keyframes scale-out {
		from {
			opacity: 1;
			transform: scale(1);
		}
		to {
			opacity: 0;
			transform: scale(0.95);
		}
	}

	@keyframes slide-in {
		from {
			transform: translateX(100%);
		}
		to {
			transform: translateX(0);
		}
	}

	@keyframes slide-out {
		from {
			transform: translateX(0);
		}
		to {
			transform: translateX(100%);
		}
	}

	/* Closing animations */
	.modal-container.closing {
		animation: fade-out 0.3s ease;
	}

	.modal-container.closing .modal-panel.center {
		animation: scale-out 0.2s ease;
	}

	.modal-container.closing .modal-panel.slide-over-panel {
		animation: slide-out 0.3s ease;
	}
</style>
