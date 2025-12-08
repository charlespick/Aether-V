<script lang="ts">
	import { page } from '$app/stores';
	
	const navItems = [
		{ label: 'Overview', path: '/', icon: 'cloud' },
		{ separator: true },
		{ label: 'Cluster 1', path: '/cluster/1', icon: 'cluster', type: 'cluster' },
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
						<span class="nav-icon">
							{#if item.icon === 'cloud'}
								<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
									<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"></path>
								</svg>
							{:else if item.icon === 'cluster'}
								<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
									<rect x="3" y="3" width="7" height="7"></rect>
									<rect x="14" y="3" width="7" height="7"></rect>
									<rect x="14" y="14" width="7" height="7"></rect>
									<rect x="3" y="14" width="7" height="7"></rect>
								</svg>
							{:else if item.icon === 'warning'}
								<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
									<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>
									<line x1="12" y1="9" x2="12" y2="13"></line>
									<line x1="12" y1="17" x2="12.01" y2="17"></line>
								</svg>
							{/if}
						</span>
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
			<svg class="settings-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
				<circle cx="12" cy="12" r="3"></circle>
				<path d="M12 1v6m0 6v6"></path>
				<path d="m1 12 6 0m6 0h6"></path>
				<path d="m4.93 4.93 4.24 4.24m5.66 5.66 4.24 4.24"></path>
				<path d="m19.07 4.93-4.24 4.24m-5.66 5.66-4.24 4.24"></path>
			</svg>
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

	.nav-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
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

	.settings-icon {
		flex-shrink: 0;
	}

	.settings-label {
		font-size: 0.875rem;
		font-weight: 500;
	}
</style>
