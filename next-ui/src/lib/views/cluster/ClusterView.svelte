<script lang="ts">
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import ViewLoader from '$lib/components/ViewLoader.svelte';
	import { useAsyncData } from '$lib/composables/useAsyncData';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	import type { Host, VM } from '$lib/stores/inventoryStore';

	const environmentName = inventoryStore.environmentName;

	interface Props {
		clusterName: string;
	}

	let { clusterName }: Props = $props();

	interface ClusterData {
		name: string;
		hosts: Host[];
		vms: VM[];
	}

	// Fetch cluster data from shared inventory store
	const clusterData = useAsyncData<ClusterData>(
		async () => {
			const inventory = inventoryStore.getData();
			
			if (!inventory) {
				throw new Error('Inventory data not available');
			}
			
			const clusterHosts = inventory.hosts.filter(h => h.cluster === clusterName);
			const clusterVMs = inventory.vms.filter(vm => {
				const vmHost = inventory.hosts.find(h => h.hostname === vm.host);
				return vmHost && vmHost.cluster === clusterName;
			});
			
			return {
				name: clusterName,
				hosts: clusterHosts,
				vms: clusterVMs
			};
		},
		{
			cache: false, // Inventory store handles caching
			refetchOnMount: true
		}
	);

	// Re-fetch data when clusterName changes
	$effect(() => {
		clusterName; // Track clusterName dependency
		clusterData.execute();
	});

	const totalCPU = $derived(
		$clusterData.data?.hosts.reduce((sum, h) => sum + (h.total_cpu_cores || 0), 0) || 0
	);
	
	const totalMemory = $derived(
		$clusterData.data?.hosts.reduce((sum, h) => sum + (h.total_memory_gb || 0), 0).toFixed(2) || '0'
	);
</script>

<svelte:head>
	<title>{$environmentName} - {clusterName}</title>
</svelte:head>

<ViewLoader loading={$clusterData.loading} error={$clusterData.error} skeleton="cluster">
	{#if $clusterData.data}
		<div class="view-container">
			<div class="page-header">
				<h1>{clusterName}</h1>
				<p class="subtitle">Cluster Overview</p>
			</div>
			
			<div class="stats-grid">
				<div class="stat-card">
					<div class="stat-label">Hosts</div>
					<div class="stat-value">{$clusterData.data.hosts.length}</div>
				</div>
				<div class="stat-card">
					<div class="stat-label">Virtual Machines</div>
					<div class="stat-value">{$clusterData.data.vms.length}</div>
				</div>
				<div class="stat-card">
					<div class="stat-label">Total CPU Cores</div>
					<div class="stat-value">{totalCPU}</div>
				</div>
				<div class="stat-card">
					<div class="stat-label">Total Memory</div>
					<div class="stat-value">{totalMemory} GB</div>
				</div>
			</div>

			<div class="section">
				<h2>Hosts in Cluster</h2>
				{#if $clusterData.data.hosts.length > 0}
					<div class="host-grid">
						{#each $clusterData.data.hosts as host}
							<button
								type="button"
								class="host-card"
								onclick={() => goto(`${base}/host/${encodeURIComponent(host.hostname)}`)}
							>
								<h3>{host.hostname.split('.')[0]}</h3>
								<div class="host-status" data-connected={host.connected}>
									{host.connected ? 'Connected' : 'Disconnected'}
								</div>
							</button>
						{/each}
					</div>
				{:else}
					<div class="empty-state">
						<p>No hosts in this cluster</p>
					</div>
				{/if}
			</div>

			<div class="section">
				<h2>Virtual Machines</h2>
				{#if $clusterData.data.vms.length > 0}
					<div class="vm-table">
						<div class="table-header">
							<div>Name</div>
							<div>Host</div>
							<div>State</div>
						</div>
						{#each $clusterData.data.vms as vm}
							<button
								type="button"
								class="table-row"
								onclick={() => goto(`${base}/virtual-machine/${encodeURIComponent(vm.id)}`)}
							>
								<div class="vm-name">{vm.name}</div>
								<div>{vm.host.split('.')[0]}</div>
								<div class="vm-state" data-state={vm.state.toLowerCase()}>
									{vm.state}
								</div>
							</button>
						{/each}
					</div>
				{:else}
					<div class="empty-state">
						<p>No virtual machines in this cluster</p>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</ViewLoader>

<style>
	.view-container {
		max-width: 1400px;
		margin: 0 auto;
	}

	.page-header h1 {
		font-size: 2rem;
		font-weight: 700;
		margin: 0 0 0.5rem 0;
		color: var(--text-primary);
	}

	.subtitle {
		color: var(--text-secondary);
		margin: 0 0 1.5rem 0;
		font-size: 0.875rem;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 1rem;
		margin-bottom: 2rem;
	}

	.stat-card {
		background-color: var(--bg-tertiary);
		padding: 1.5rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
	}

	.stat-label {
		color: var(--text-secondary);
		font-size: 0.875rem;
		margin-bottom: 0.5rem;
	}

	.stat-value {
		font-size: 2rem;
		font-weight: 700;
		color: var(--text-primary);
	}

	.section {
		margin-bottom: 2rem;
	}

	.section h2 {
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0 0 1rem 0;
		color: var(--text-primary);
	}

	.host-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
		gap: 1rem;
	}

	.host-card {
		background-color: var(--bg-tertiary);
		padding: 1.5rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		cursor: pointer;
		transition: all var(--transition-fast);
		text-align: left;
		width: 100%;
	}

	.host-card:hover {
		background-color: var(--bg-hover);
		border-color: var(--border-color-hover);
		transform: translateY(-2px);
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
	}

	.host-card h3 {
		font-size: 1rem;
		font-weight: 600;
		margin: 0 0 0.5rem 0;
		color: var(--text-primary);
	}

	.host-status {
		font-size: 0.875rem;
		padding: 0.25rem 0.75rem;
		border-radius: var(--radius-sm);
		display: inline-block;
	}

	.host-status[data-connected="true"] {
		background-color: var(--success);
		color: white;
	}

	.host-status[data-connected="false"] {
		background-color: var(--error);
		color: white;
	}

	.vm-table {
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		overflow: hidden;
	}

	.table-header {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 2px solid var(--border-color);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-primary);
	}

	.table-row {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 1px solid var(--border-color);
		transition: background-color var(--transition-fast);
		cursor: pointer;
		text-align: left;
		width: 100%;
		border-left: none;
		border-right: none;
		border-top: none;
		background: transparent;
	}

	.table-row:last-child {
		border-bottom: none;
	}

	.table-row:hover {
		background-color: var(--bg-hover);
	}

	.vm-name {
		font-weight: 500;
		color: var(--text-primary);
	}

	.table-row > div {
		color: var(--text-primary);
	}

	.vm-state {
		font-size: 0.875rem;
		padding: 0.25rem 0.75rem;
		border-radius: var(--radius-sm);
		display: inline-block;
		text-align: center;
	}

	.vm-state[data-state="running"] {
		background-color: var(--success);
		color: white;
	}

	.vm-state[data-state="off"] {
		background-color: var(--text-tertiary);
		color: white;
	}

	.vm-state[data-state="saved"],
	.vm-state[data-state="paused"] {
		background-color: var(--warning);
		color: white;
	}

	.empty-state {
		background-color: var(--bg-tertiary);
		padding: 3rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		text-align: center;
		color: var(--text-secondary);
	}
</style>
