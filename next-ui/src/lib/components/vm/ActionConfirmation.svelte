<script lang="ts">
	import { onMount } from 'svelte';
	import { clickOutside } from '$lib/actions/clickOutside';

	interface Props {
		action: string;
		vmName: string;
		buttonElement: HTMLElement;
		onConfirm: () => void;
		onCancel: () => void;
	}

	let { action, vmName, buttonElement, onConfirm, onCancel }: Props = $props();

	let overlayElement: HTMLDivElement;
	let positioned = $state(false);
	let positionAbove = $state(false);

	const confirmationCopy = $derived.by(() => {
		const normalized = action.toLowerCase();

		if (normalized === 'shutdown') {
			return {
				title: 'Confirm shut down',
				message: `Shut down ${vmName}? This requests a graceful shutdown from the guest operating system.`,
				confirmLabel: 'Shut down'
			};
		}

		if (normalized === 'stop') {
			return {
				title: 'Confirm turn off',
				message: `Turn off ${vmName}? This immediately powers off the VM and may cause data loss.`,
				confirmLabel: 'Turn off'
			};
		}

		if (normalized === 'reset') {
			return {
				title: 'Confirm reset',
				message: `Reset ${vmName}? This power cycles the VM and will interrupt any running processes.`,
				confirmLabel: 'Reset'
			};
		}

		if (normalized === 'delete') {
			return {
				title: 'Confirm delete',
				message: `Delete ${vmName}? This permanently removes the VM registration and disks from the host.`,
				confirmLabel: 'Delete'
			};
		}

		return {
			title: 'Confirm action',
			message: `Proceed with ${normalized} action on ${vmName}?`,
			confirmLabel: 'Confirm'
		};
	});

	function positionOverlay() {
		if (!overlayElement || !buttonElement) return;

		const buttonRect = buttonElement.getBoundingClientRect();
		const overlayRect = overlayElement.getBoundingClientRect();
		const viewportWidth = document.documentElement.clientWidth;
		const viewportHeight = window.innerHeight;
		const scrollY = window.scrollY || document.documentElement.scrollTop;
		const scrollX = window.scrollX || document.documentElement.scrollLeft;
		const edgeMargin = 20;

		let top = scrollY + buttonRect.bottom + 8;
		let alignAbove = false;

		if (top + overlayRect.height > scrollY + viewportHeight - edgeMargin) {
			top = scrollY + buttonRect.top - overlayRect.height - 8;
			alignAbove = true;
		}

		if (top < scrollY + edgeMargin) {
			top = scrollY + edgeMargin;
		}

		let left = scrollX + buttonRect.left + buttonRect.width / 2 - overlayRect.width / 2;
		const minLeft = scrollX + edgeMargin;
		const maxLeft = scrollX + viewportWidth - overlayRect.width - edgeMargin;
		if (left < minLeft) {
			left = minLeft;
		} else if (left > maxLeft) {
			left = Math.max(minLeft, maxLeft);
		}

		overlayElement.style.top = `${Math.round(top)}px`;
		overlayElement.style.left = `${Math.round(left)}px`;
		positionAbove = alignAbove;
		positioned = true;
	}

	function handleConfirm() {
		onConfirm();
	}

	function handleCancel() {
		onCancel();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			onCancel();
		}
	}

	onMount(() => {
		positionOverlay();
		window.addEventListener('resize', positionOverlay);
		window.addEventListener('scroll', positionOverlay, true);
		document.addEventListener('keydown', handleKeydown);

		return () => {
			window.removeEventListener('resize', positionOverlay);
			window.removeEventListener('scroll', positionOverlay, true);
			document.removeEventListener('keydown', handleKeydown);
		};
	});
</script>

<div
	bind:this={overlayElement}
	class="vm-action-confirm"
	class:vm-action-confirm--above={positionAbove}
	class:visible={positioned}
	role="dialog"
	aria-modal="false"
	use:clickOutside={onCancel}
>
	<div class="vm-action-confirm__title">{confirmationCopy.title}</div>
	<div class="vm-action-confirm__message">{confirmationCopy.message}</div>
	<div class="vm-action-confirm__actions">
		<button type="button" class="vm-action-confirm__cancel" onclick={handleCancel}>
			Cancel
		</button>
		<button type="button" class="vm-action-confirm__confirm" onclick={handleConfirm}>
			{confirmationCopy.confirmLabel}
		</button>
	</div>
</div>

<style>
	.vm-action-confirm {
		position: absolute;
		background: var(--bg-primary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
		padding: 1.25rem;
		min-width: 320px;
		max-width: 420px;
		z-index: 1000;
		opacity: 0;
		visibility: hidden;
		transform: translateY(-8px);
		transition: all 0.2s ease;
	}

	.vm-action-confirm.visible {
		opacity: 1;
		visibility: visible;
		transform: translateY(0);
	}

	.vm-action-confirm--above.visible {
		transform: translateY(0);
	}

	.vm-action-confirm--above {
		transform: translateY(8px);
	}

	.vm-action-confirm__title {
		font-size: 1rem;
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: 0.5rem;
	}

	.vm-action-confirm__message {
		font-size: 0.875rem;
		color: var(--text-secondary);
		line-height: 1.5;
		margin-bottom: 1rem;
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
		transition: all 0.15s ease;
		border: none;
	}

	.vm-action-confirm__cancel {
		background: var(--bg-tertiary);
		color: var(--text-primary);
	}

	.vm-action-confirm__cancel:hover {
		background: var(--bg-quaternary);
	}

	.vm-action-confirm__confirm {
		background: var(--primary);
		color: white;
	}

	.vm-action-confirm__confirm:hover {
		opacity: 0.9;
	}
</style>
