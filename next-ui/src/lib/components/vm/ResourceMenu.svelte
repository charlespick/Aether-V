<script lang="ts">
	import Icon from '$lib/components/common/Icon.svelte';
	import { onMount } from 'svelte';
	import { clickOutside } from '$lib/actions/clickOutside';

	interface Props {
		resourceType: 'disk' | 'nic';
		resourceId: string;
		onEdit: () => void;
		onDelete: () => void;
		onClose: () => void;
		buttonElement: HTMLElement;
	}

	let { resourceType, resourceId, onEdit, onDelete, onClose, buttonElement }: Props = $props();

	let menuElement: HTMLDivElement;
	let positioned = $state(false);

	const editLabel = resourceType === 'disk' ? 'Edit Disk' : 'Edit Network Adapter';
	const deleteLabel = resourceType === 'disk' ? 'Delete Disk' : 'Delete Network Adapter';

	function positionMenu() {
		if (!menuElement || !buttonElement) return;

		const buttonRect = buttonElement.getBoundingClientRect();
		const menuRect = menuElement.getBoundingClientRect();
		const viewportWidth = window.innerWidth;
		const viewportHeight = window.innerHeight;
		const edgeMargin = 20;

		// Default positioning: below the button, aligned to the left
		let top = buttonRect.bottom + 4;
		let left = buttonRect.left;

		// Check if menu would extend past right edge of viewport
		if (left + menuRect.width > viewportWidth - edgeMargin) {
			// Align to the right edge of the button instead
			left = buttonRect.right - menuRect.width;
		}

		// Ensure menu doesn't go past left edge
		if (left < edgeMargin) {
			left = edgeMargin;
		}

		// Check if menu would extend past bottom edge of viewport
		if (buttonRect.bottom + menuRect.height > viewportHeight - edgeMargin) {
			// Position above the button instead
			top = buttonRect.top - menuRect.height - 4;
		}

		// Ensure menu doesn't go past top edge
		if (top < edgeMargin) {
			top = edgeMargin;
		}

		// Apply final position
		menuElement.style.top = `${Math.round(top)}px`;
		menuElement.style.left = `${Math.round(left)}px`;
		positioned = true;
	}

	function handleEdit() {
		onEdit();
		onClose();
	}

	function handleDelete() {
		onDelete();
		onClose();
	}

	onMount(() => {
		positionMenu();
		window.addEventListener('resize', positionMenu);
		window.addEventListener('scroll', positionMenu, true);

		return () => {
			window.removeEventListener('resize', positionMenu);
			window.removeEventListener('scroll', positionMenu, true);
		};
	});
</script>

<div
	bind:this={menuElement}
	class="resource-menu"
	class:visible={positioned}
	role="menu"
	use:clickOutside={onClose}
>
	<button type="button" class="resource-menu-item" onclick={handleEdit} role="menuitem">
		<Icon name="edit" size={18} />
		<span>{editLabel}</span>
	</button>
	<button
		type="button"
		class="resource-menu-item resource-menu-item--danger"
		onclick={handleDelete}
		role="menuitem"
	>
		<Icon name="delete" size={18} />
		<span>{deleteLabel}</span>
	</button>
</div>

<style>
	.resource-menu {
		position: fixed;
		background: var(--bg-secondary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
		min-width: 180px;
		padding: 0.25rem;
		z-index: 1000;
		opacity: 0;
		visibility: hidden;
		transition: opacity 0.2s ease, visibility 0.2s ease;
	}

	.resource-menu.visible {
		opacity: 1;
		visibility: visible;
	}

	.resource-menu-item {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		width: 100%;
		padding: 0.625rem 0.875rem;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		color: var(--text-primary);
		font-size: 0.875rem;
		cursor: pointer;
		transition: background-color 0.15s ease;
	}

	.resource-menu-item:hover {
		background-color: var(--bg-tertiary);
	}

	.resource-menu-item--danger {
		color: var(--danger);
	}

	.resource-menu-item--danger:hover {
		background-color: rgba(239, 68, 68, 0.1);
	}
</style>
