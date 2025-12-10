<script lang="ts">
	import { themeStore } from '$lib/stores/themeStore';
	import Icon from './Icon.svelte';

	const theme = $derived($themeStore);
	
	function handleToggle() {
		themeStore.toggle();
	}

	// Get icon and label based on current mode
	const iconName = $derived(() => {
		switch (theme.mode) {
			case 'light':
				return 'light_mode';
			case 'dark':
				return 'dark_mode';
			case 'system':
				return 'contrast';
			default:
				return 'dark_mode';
		}
	});

	const label = $derived(() => {
		switch (theme.mode) {
			case 'light':
				return 'Light theme';
			case 'dark':
				return 'Dark theme';
			case 'system':
				return 'System theme';
			default:
				return 'Theme';
		}
	});
</script>

<button 
	class="theme-toggle" 
	onclick={handleToggle}
	aria-label="Toggle theme"
	title={label()}
>
	<Icon name={iconName()} />
	<span class="theme-label">{label()}</span>
</button>

<style>
	.theme-toggle {
		display: flex;
		align-items: center;
		gap: var(--spacing-sm);
		padding: var(--spacing-sm) var(--spacing-md);
		background-color: var(--bg-secondary);
		color: var(--text-primary);
		border-radius: var(--radius-md);
		font-size: 0.875rem;
		font-weight: 500;
		transition: background-color var(--transition-fast), color var(--transition-fast);
	}

	.theme-toggle:hover {
		background-color: var(--bg-hover);
	}

	.theme-toggle:active {
		transform: scale(0.98);
	}

	.theme-label {
		white-space: nowrap;
	}

	@media (max-width: 768px) {
		.theme-label {
			display: none;
		}
		
		.theme-toggle {
			padding: var(--spacing-sm);
		}
	}
</style>
