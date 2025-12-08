<script lang="ts">
	import { page } from '$app/stores';
	import Icon from './Icon.svelte';
	
	const navItems = [
		{ label: 'Overview', path: '/', icon: 'cloud' },
		{ separator: true },
		{ label: 'Cluster 1', path: '/cluster/1', icon: 'grid_view', type: 'cluster' },
		{ label: 'Disconnected Hosts', path: '/disconnected', icon: 'warning', badge: 0 }
	];
	
	let currentPath = $derived($page.url.pathname);
</script>

<nav class="sidebar">
	<ul class="nav-list">
		{#each navItems as item}
			{#if item.separator}
				<li class="nav-separator"></li>
			{:else}
				<li class="nav-item" class:active={currentPath === item.path}>
					<a href={item.path} class="nav-link">
						<Icon name={item.icon} size={20} />
						<span class="nav-label">{item.label}</span>
						{#if item.badge !== undefined && item.badge > 0}
							<span class="badge">{item.badge}</span>
						{/if}
					</a>
				</li>
			{/if}
		{/each}
	</ul>
	
	<div class="sidebar-footer">
		<button class="settings-btn" title="Settings">
			<Icon name="settings" size={20} />
			<span class="settings-label">Settings</span>
		</button>
	</div>
</nav>

<style>
	.sidebar {
		width: 240px;
		background-color: var(--bg-tertiary);
		border-right: 1px solid var(--border-color);
		display: flex;
		flex-direction: column;
		overflow-y: auto;
	}

	.nav-list {
		list-style: none;
		margin: 0;
		padding: 1rem 0.75rem;
		flex: 1;
	}

	.nav-item {
		margin-bottom: 0.25rem;
	}

	.nav-link {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.625rem 0.75rem;
		border-radius: var(--radius-md);
		color: var(--text-secondary);
		transition: background-color var(--transition-fast), color var(--transition-fast);
		text-decoration: none;
	}

	.nav-link:hover {
		background-color: var(--bg-hover);
		color: var(--text-primary);
	}

	.nav-item.active .nav-link {
		background-color: var(--accent-primary);
		color: white;
	}

	.nav-label {
		flex: 1;
		font-size: 0.875rem;
		font-weight: 500;
	}

	.nav-separator {
		height: 1px;
		background-color: var(--border-subtle);
		margin: 0.75rem 0;
	}

	.badge {
		background-color: var(--error);
		color: white;
		font-size: 0.75rem;
		font-weight: 600;
		padding: 0.125rem 0.5rem;
		border-radius: 999px;
		min-width: 20px;
		text-align: center;
	}

	.sidebar-footer {
		padding: 1rem 0.75rem;
		border-top: 1px solid var(--border-color);
	}

	.settings-btn {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		width: 100%;
		padding: 0.625rem 0.75rem;
		color: var(--text-secondary);
		border-radius: var(--radius-md);
		transition: background-color var(--transition-fast), color var(--transition-fast);
	}

	.settings-btn:hover {
		background-color: var(--bg-hover);
		color: var(--text-primary);
	}

	.settings-label {
		font-size: 0.875rem;
		font-weight: 500;
	}
</style>
