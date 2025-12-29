<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import Icon from './Icon.svelte';
	import SettingsModal from '$lib/components/modals/SettingsModal.svelte';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	import type { InventoryData } from '$lib/stores/inventoryStore';

	// Subscribe to shared inventory store
	const inventoryData = inventoryStore.data;
	
	let showSettings = $state(false);

	let expandedClusters = $state(new Set<string>());
	let expandedHosts = $state(new Set<string>());
	
	let currentPath = $derived($page.url.pathname);

	// Derived inventory for easier access
	let inventory = $derived($inventoryData);

	// Load expanded state from localStorage
	onMount(() => {
		const savedClusters = localStorage.getItem('nav.expandedClusters');
		const savedHosts = localStorage.getItem('nav.expandedHosts');
		
		if (savedClusters) {
			try {
				expandedClusters = new Set(JSON.parse(savedClusters));
			} catch (e) {
				console.warn('Failed to parse saved cluster state:', e);
			}
		}
		
		if (savedHosts) {
			try {
				expandedHosts = new Set(JSON.parse(savedHosts));
			} catch (e) {
				console.warn('Failed to parse saved host state:', e);
			}
		}
	});

	function toggleCluster(clusterName: string) {
		if (expandedClusters.has(clusterName)) {
			expandedClusters.delete(clusterName);
		} else {
			expandedClusters.add(clusterName);
		}
		expandedClusters = new Set(expandedClusters); // Trigger reactivity
		localStorage.setItem('nav.expandedClusters', JSON.stringify([...expandedClusters]));
	}

	function toggleHost(hostname: string) {
		if (expandedHosts.has(hostname)) {
			expandedHosts.delete(hostname);
		} else {
			expandedHosts.add(hostname);
		}
		expandedHosts = new Set(expandedHosts); // Trigger reactivity
		localStorage.setItem('nav.expandedHosts', JSON.stringify([...expandedHosts]));
	}

	function getVmStateMeta(state: string) {
		const stateMap: Record<string, { icon: string; color: string }> = {
			'Running': { icon: 'play_circle', color: 'var(--success)' },
			'Off': { icon: 'power_settings_new', color: 'var(--text-tertiary)' },
			'Saved': { icon: 'pause_circle', color: 'var(--warning)' },
			'Paused': { icon: 'pause_circle', color: 'var(--warning)' }
		};
		return stateMap[state] || { icon: 'power_settings_new', color: 'var(--text-tertiary)' };
	}

	// Group VMs by host
	function getVmsByHost(vms: any[]) {
		const grouped: Record<string, any[]> = {};
		vms.forEach(vm => {
			// Skip VMs without valid IDs
			if (!vm.id) return;
			
			if (!grouped[vm.host]) {
				grouped[vm.host] = [];
			}
			grouped[vm.host].push(vm);
		});
		return grouped;
	}

	// Get hosts for a cluster
	function getClusterHosts(clusterName: string, hosts: any[]) {
		return hosts.filter(h => h.cluster === clusterName);
	}

	// Check if current path matches nav item
	function isActive(path: string): boolean {
		const fullPath = base + path;
		return currentPath === fullPath || currentPath === path;
	}
</script>

<nav class="sidebar">
	<ul class="nav-list">
		<li class="nav-item" class:active={isActive('/')}>
			<a href="{base}/" class="nav-link">
				<Icon name="cloud" size={20} />
				<span class="nav-label">Overview</span>
			</a>
		</li>
		
		<li class="nav-separator overview-separator"></li>
		
		{#if inventory}
			{#if inventory.clusters.length === 0}
				<li class="nav-item empty-state">
					<span class="empty-text">No hosts connected</span>
				</li>
			{:else}
				{@const vmsByHost = getVmsByHost(inventory.vms)}
				{#each inventory.clusters as cluster}
					{@const clusterHosts = getClusterHosts(cluster.name, inventory.hosts)}
					{@const isExpanded = expandedClusters.has(cluster.name)}
					<li class="nav-group" class:expanded={isExpanded} data-cluster={cluster.name}>
						<div class="nav-item group-header" class:active={isActive(`/cluster/${cluster.name}`)}>
							<a href="{base}/cluster/{encodeURIComponent(cluster.name)}" class="nav-link" onclick={(e) => {
								if (!isExpanded) {
									e.preventDefault();
									toggleCluster(cluster.name);
								}
							}}>
								<Icon name="circles_ext" size={20} />
								<span class="nav-label">{cluster.name}</span>
							</a>
							<button
								class="expand-btn"
								onclick={() => toggleCluster(cluster.name)}
								aria-label={isExpanded ? 'Collapse' : 'Expand'}
							>
								<Icon name="arrow_drop_down" size={20} />
							</button>
						</div>
						
						{#if isExpanded}
							<ul class="sub-list">
								{#each clusterHosts as host}
									{@const hostVMs = vmsByHost[host.hostname] || []}
									{@const hostExpanded = expandedHosts.has(host.hostname)}
									{@const shortName = host.hostname.split('.')[0]}
									<li class="nav-group sub-group" class:expanded={hostExpanded} data-host={host.hostname}>
										<div class="sub-item group-header" class:active={isActive(`/host/${host.hostname}`)}>
											<a href="{base}/host/{encodeURIComponent(host.hostname)}" class="nav-link" onclick={(e) => {
												if (!hostExpanded && hostVMs.length > 0) {
													e.preventDefault();
													toggleHost(host.hostname);
												}
											}}>
												<Icon name="host" size={18} />
												<span class="nav-label">{shortName}</span>
											</a>
											{#if hostVMs.length > 0}
												<button
													class="expand-btn"
													onclick={() => toggleHost(host.hostname)}
													aria-label={hostExpanded ? 'Collapse' : 'Expand'}
												>
													<Icon name="arrow_drop_down" size={18} />
												</button>
											{/if}
										</div>
										
										{#if hostExpanded && hostVMs.length > 0}
											<ul class="vm-list">
												{#each hostVMs as vm}
													{@const vmMeta = getVmStateMeta(vm.state)}
													<li class="vm-item" class:active={isActive(`/virtual-machine/${vm.id}`)}>
														<a href="{base}/virtual-machine/{encodeURIComponent(vm.id)}" class="nav-link">
															<span class="vm-status" style="color: {vmMeta.color}">
																<Icon name={vmMeta.icon} size={12} />
															</span>
															<span class="vm-name">{vm.name}</span>
														</a>
													</li>
												{/each}
											</ul>
										{/if}
									</li>
								{/each}
							</ul>
						{/if}
					</li>
				{/each}
			{/if}
			
			{#if inventory.disconnected_hosts.length > 0}
				<li class="nav-item" class:active={isActive('/disconnected-hosts')}>
					<a href="{base}/disconnected-hosts" class="nav-link">
						<Icon name="warning" size={20} />
						<span class="nav-label">Disconnected Hosts</span>
						<span class="badge">{inventory.disconnected_hosts.length}</span>
					</a>
				</li>
			{/if}
		{:else}
			<li class="nav-item empty-state">
				<span class="empty-text">Loading...</span>
			</li>
		{/if}
	</ul>
	
	<div class="sidebar-footer">
		<button class="settings-btn" title="Settings" onclick={() => showSettings = true}>
			<Icon name="settings" size={20} />
			<span class="settings-label">Settings</span>
		</button>
	</div>
</nav>

<SettingsModal bind:isOpen={showSettings} onClose={() => showSettings = false} />

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
		position: relative;
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
		flex: 1;
	}

	/* Hover and active states for regular nav items (Overview, Disconnected Hosts, VMs) */
	/* Exclude group headers - they handle their own styling */
	.nav-link:hover {
		background-color: rgba(0, 0, 0, 0.03);
		color: var(--text-primary);
	}

	:global([data-theme="dark"]) .nav-link:hover {
		background-color: rgba(255, 255, 255, 0.08);
	}

	/* Active state for regular nav items - exclude group-headers */
	.nav-item:not(.group-header).active > .nav-link,
	.vm-item.active .nav-link {
		background-color: rgba(0, 0, 0, 0.04);
		color: var(--text-primary);
		font-weight: 600;
	}

	:global([data-theme="dark"]) .nav-item:not(.group-header).active > .nav-link,
	:global([data-theme="dark"]) .vm-item.active .nav-link {
		background-color: rgba(255, 255, 255, 0.1);
	}

	/* Hover and active states for group headers (clusters and hosts with expand buttons) */
	.group-header:hover {
		background-color: rgba(0, 0, 0, 0.03);
	}

	:global([data-theme="dark"]) .group-header:hover {
		background-color: rgba(255, 255, 255, 0.08);
	}

	/* Remove hover background from nav-link when inside group-header */
	.group-header .nav-link:hover {
		background-color: transparent;
	}

	/* Active state for cluster group headers */
	.nav-item.group-header.active {
		background-color: rgba(0, 0, 0, 0.04);
		font-weight: 600;
	}

	:global([data-theme="dark"]) .nav-item.group-header.active {
		background-color: rgba(255, 255, 255, 0.1);
	}

	/* Active state for host group headers (sub-items) */
	.sub-item.group-header.active {
		background-color: rgba(0, 0, 0, 0.04);
		font-weight: 600;
	}

	:global([data-theme="dark"]) .sub-item.group-header.active {
		background-color: rgba(255, 255, 255, 0.1);
	}

	/* Ensure text color changes in group headers */
	.group-header:hover .nav-link,
	.nav-item.group-header.active .nav-link,
	.sub-item.group-header.active .nav-link {
		color: var(--text-primary);
	}

	.nav-label {
		flex: 1;
		font-size: 0.875rem;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.nav-separator {
		height: 1px;
		background-color: var(--border-color);
		margin: 0.75rem 0;
	}

	.nav-separator.overview-separator {
		margin: 12px 0;
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

	/* Navigation groups (collapsible clusters and hosts) */
	.nav-group {
		list-style: none;
		margin-bottom: 0.25rem;
	}

	.group-header {
		display: flex;
		align-items: center;
		position: relative;
		padding: 0.625rem 0.75rem;
		border-radius: var(--radius-md);
		transition: background-color var(--transition-fast);
	}

	.group-header .nav-link {
		flex: 1;
		padding: 0;
		border-radius: 0;
	}

	.expand-btn {
		padding: 0.25rem;
		color: var(--text-secondary);
		background: transparent;
		border: none;
		cursor: pointer;
		transition: color var(--transition-fast), background-color var(--transition-fast);
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		margin: -0.25rem;
		margin-left: auto;
	}

	.expand-btn:hover {
		color: var(--text-primary);
		background-color: rgba(0, 0, 0, 0.05);
	}

	:global([data-theme="dark"]) .expand-btn:hover {
		background-color: rgba(255, 255, 255, 0.1);
	}

	/* Rotate only the icon inside the expand button */
	.expand-btn :global(.icon) {
		transition: transform var(--transition-fast);
	}

	.nav-group:not(.expanded) .expand-btn :global(.icon) {
		transform: rotate(-90deg);
	}

	/* Sub-lists (hosts under clusters) */
	.sub-list {
		list-style: none;
		margin: 0;
		padding-left: 1.5rem;
		display: none;
	}

	.nav-group.expanded > .sub-list {
		display: block;
	}

	.sub-group {
		margin-bottom: 0.25rem;
	}

	.sub-item {
		margin-bottom: 0.25rem;
	}

	/* sub-item.group-header inherits padding from .group-header */
	.sub-item.group-header {
		padding: 0.5rem 0.625rem;
	}

	.sub-item .nav-link {
		font-size: 0.8125rem;
	}

	/* Override for sub-item nav-links inside group-header */
	.sub-item.group-header .nav-link {
		padding: 0;
		border-radius: 0;
	}

	/* VM lists (VMs under hosts) */
	.vm-list {
		list-style: none;
		margin: 0;
		padding-left: 1.5rem;
		display: none;
	}

	.sub-group.expanded .vm-list {
		display: block;
	}

	.vm-item {
		margin-bottom: 0.125rem;
	}

	.vm-item .nav-link {
		font-size: 0.75rem;
		padding: 0.375rem 0.5rem;
		gap: 0.5rem;
	}

	.vm-status {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.vm-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.empty-state {
		padding: 1rem 0.5rem;
		text-align: center;
	}

	.empty-text {
		color: var(--text-tertiary);
		font-size: 0.75rem;
	}

	.sidebar-footer {
		padding: 1rem 0.75rem;
		position: relative;
	}

	.sidebar-footer::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0.75rem;
		right: 0.75rem;
		height: 1px;
		background-color: var(--border-color);
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
