<script lang="ts">
	import { getActionConfirmationCopy } from '$lib/utils/vm';
	import { onMount } from 'svelte';

	interface Props {
		action: string;
		vmName: string;
		onConfirm: () => void;
		onCancel: () => void;
		buttonRef?: HTMLElement;
	}

	let { action, vmName, onConfirm, onCancel, buttonRef }: Props = $props();

	let dialogEl: HTMLDivElement | undefined = $state();
	let visible = $state(false);

	const copy = $derived(getActionConfirmationCopy(action, vmName));

	onMount(() => {
		// Position the dialog
		if (dialogEl && buttonRef) {
			positionDialog();
		}

		// Show with animation
		setTimeout(() => {
			visible = true;
		}, 10);

		// Handle outside clicks
		const handleClickOutside = (e: MouseEvent) => {
			if (dialogEl && !dialogEl.contains(e.target as Node)) {
				if (buttonRef && buttonRef.contains(e.target as Node)) {
					return; // Don't close if clicking the button
				}
				onCancel();
			}
		};

		// Handle escape key
		const handleEscape = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				e.preventDefault();
				onCancel();
			}
		};

		// Handle window resize/scroll
		const handleReposition = () => {
			if (dialogEl && buttonRef) {
				positionDialog();
			}
		};

		document.addEventListener('mousedown', handleClickOutside, true);
		document.addEventListener('keydown', handleEscape, true);
		window.addEventListener('resize', handleReposition, true);
		window.addEventListener('scroll', handleReposition, true);

		return () => {
			document.removeEventListener('mousedown', handleClickOutside, true);
			document.removeEventListener('keydown', handleEscape, true);
			window.removeEventListener('resize', handleReposition, true);
			window.removeEventListener('scroll', handleReposition, true);
		};
	});

	function positionDialog() {
		if (!dialogEl || !buttonRef) return;

		const buttonRect = buttonRef.getBoundingClientRect();
		const dialogRect = dialogEl.getBoundingClientRect();
		const viewportHeight = window.innerHeight;
		const scrollY = window.scrollY || document.documentElement.scrollTop;
		const scrollX = window.scrollX || document.documentElement.scrollLeft;
		const edgeMargin = 20;

		// Default: position below button
		let top = scrollY + buttonRect.bottom + 8;
		let alignAbove = false;

		// Check if there's enough space below
		if (top + dialogRect.height > scrollY + viewportHeight - edgeMargin) {
			// Position above instead
			top = scrollY + buttonRect.top - dialogRect.height - 8;
			alignAbove = true;
		}

		// Ensure doesn't go above viewport
		if (top < scrollY + edgeMargin) {
			top = scrollY + edgeMargin;
		}

		// Center horizontally relative to button
		let left = scrollX + buttonRect.left + buttonRect.width / 2 - dialogRect.width / 2;

		// Keep within viewport bounds
		const minLeft = scrollX + edgeMargin;
		const maxLeft = scrollX + window.innerWidth - dialogRect.width - edgeMargin;
		left = Math.max(minLeft, Math.min(left, maxLeft));

		dialogEl.style.top = `${Math.round(top)}px`;
		dialogEl.style.left = `${Math.round(left)}px`;

		if (alignAbove) {
			dialogEl.classList.add('above');
		} else {
			dialogEl.classList.remove('above');
		}
	}
</script>

<div bind:this={dialogEl} class="vm-action-confirm" class:visible role="dialog" aria-modal="false">
	<div class="vm-action-confirm__title">{copy.title}</div>
	<div class="vm-action-confirm__message">{copy.message}</div>
	<div class="vm-action-confirm__actions">
		<button type="button" class="vm-action-confirm__cancel" onclick={onCancel}>Cancel</button>
		<button type="button" class="vm-action-confirm__confirm" onclick={onConfirm} autofocus>
			{copy.confirmLabel}
		</button>
	</div>
</div>

<style>
	.vm-action-confirm {
		position: absolute;
		background: var(--bg-primary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
		padding: 1.25rem;
		min-width: 300px;
		max-width: 400px;
		z-index: 1000;
		opacity: 0;
		transform: translateY(-4px);
		transition:
			opacity 0.2s ease,
			transform 0.2s ease;
		pointer-events: none;
	}

	.vm-action-confirm.visible {
		opacity: 1;
		transform: translateY(0);
		pointer-events: auto;
	}

	.vm-action-confirm.above {
		transform: translateY(4px);
	}

	.vm-action-confirm.above.visible {
		transform: translateY(0);
	}

	.vm-action-confirm__title {
		font-size: 1rem;
		font-weight: 600;
		margin-bottom: 0.5rem;
		color: var(--text-primary);
	}

	.vm-action-confirm__message {
		font-size: 0.875rem;
		color: var(--text-secondary);
		margin-bottom: 1rem;
		line-height: 1.5;
	}

	.vm-action-confirm__actions {
		display: flex;
		gap: 0.5rem;
		justify-content: flex-end;
	}

	.vm-action-confirm__cancel,
	.vm-action-confirm__confirm {
		padding: 0.5rem 1rem;
		border-radius: var(--radius-md);
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s ease;
		border: 1px solid var(--border-color);
	}

	.vm-action-confirm__cancel {
		background: var(--bg-secondary);
		color: var(--text-primary);
	}

	.vm-action-confirm__cancel:hover {
		background: var(--bg-tertiary);
	}

	.vm-action-confirm__confirm {
		background: var(--danger);
		color: white;
		border-color: var(--danger);
	}

	.vm-action-confirm__confirm:hover {
		background: var(--danger-hover, #c92a2a);
	}
</style>
