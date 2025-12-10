<script lang="ts">
	import ViewLoader from '$lib/components/ViewLoader.svelte';
	import { useAsyncData } from '$lib/composables/useAsyncData';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	import type { Host } from '$lib/stores/inventoryStore';

	const environmentName = inventoryStore.environmentName;

	// Fetch disconnected hosts from shared inventory store
	const hostsData = useAsyncData<{ hosts: Host[] }>(
		async () => {
			const inventory = inventoryStore.getData();
			
			if (!inventory) {
				throw new Error('Inventory data not available');
			}
			
			return {
				hosts: inventory.disconnected_hosts || []
			};
		},
		{
			cache: false, // Inventory store handles caching
			refetchOnMount: true
		}
	);
</script>

<svelte:head>
	<title>{$environmentName} - Disconnected Hosts</title>
</svelte:head>

<ViewLoader loading={$hostsData.loading} error={$hostsData.error} skeleton="list">
	{#if $hostsData.data}
		<div class="view-container">
			<div class="page-header">
				<h1>Disconnected Hosts</h1>
				<p class="subtitle">
					{$hostsData.data.hosts.length} 
					{$hostsData.data.hosts.length === 1 ? 'host' : 'hosts'} currently disconnected
				</p>
			</div>

			{#if $hostsData.data.hosts.length > 0}
				<div class="host-list">
					{#each $hostsData.data.hosts as host}
						<div class="host-card">
							<div class="host-info">
								<h3>{host.hostname}</h3>
								{#if host.cluster}
									<p class="cluster-name">Cluster: {host.cluster}</p>
								{/if}
								{#if host.last_seen}
									<p class="last-seen">Last seen: {new Date(host.last_seen).toLocaleString()}</p>
								{/if}
							</div>
							<div class="status-badge">
								Disconnected
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="empty-state">
					<p>No disconnected hosts</p>
					<p class="empty-subtitle">All configured hosts are currently connected</p>
				</div>
			{/if}
		</div>
	{/if}
</ViewLoader>

<style>
	.view-container {
		max-width: 1400px;
		margin: 0 auto;
	}

	.page-header {
		margin-bottom: 2rem;
	}

	.page-header h1 {
		font-size: 2rem;
		font-weight: 700;
		margin: 0 0 0.5rem 0;
	}

	.subtitle {
		color: var(--text-secondary);
		margin: 0;
	}

	.host-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.host-card {
		background-color: var(--bg-tertiary);
		padding: 1.5rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.host-info h3 {
		font-size: 1.125rem;
		font-weight: 600;
		margin: 0 0 0.5rem 0;
	}

	.cluster-name,
	.last-seen {
		font-size: 0.875rem;
		color: var(--text-secondary);
		margin: 0.25rem 0 0 0;
	}

	.status-badge {
		padding: 0.5rem 1rem;
		border-radius: var(--radius-md);
		background-color: var(--error);
		color: white;
		font-weight: 600;
		font-size: 0.875rem;
	}

	.empty-state {
		background-color: var(--bg-tertiary);
		padding: 3rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		text-align: center;
	}

	.empty-state p {
		margin: 0;
		color: var(--text-secondary);
	}

	.empty-subtitle {
		font-size: 0.875rem;
		margin-top: 0.5rem !important;
	}
</style>
