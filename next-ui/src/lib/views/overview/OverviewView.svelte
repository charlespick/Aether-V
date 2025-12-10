<script lang="ts">
	import Button from '$lib/components/common/Button.svelte';
	import Icon from '$lib/components/common/Icon.svelte';
	import ViewLoader from '$lib/components/ViewLoader.svelte';
	import { inventoryStore } from '$lib/stores/inventoryStore';

	// Subscribe to inventory store derived values
	const loading = inventoryStore.loading;
	const error = inventoryStore.error;
	const totalVMs = inventoryStore.totalVMs;
	const runningVMs = inventoryStore.runningVMs;
	const stoppedVMs = inventoryStore.stoppedVMs;
	const totalClusters = inventoryStore.totalClusters;
	const totalHosts = inventoryStore.totalHosts;
	const connectedHosts = inventoryStore.connectedHosts;
	const disconnectedCount = inventoryStore.disconnectedCount;
	const environmentName = inventoryStore.environmentName;

	// Derived stat cards from inventory data
	const stats = $derived([
		{ label: 'Total VMs', value: String($totalVMs), status: 'success' },
		{ label: 'Running', value: String($runningVMs), status: 'success' },
		{ label: 'Stopped', value: String($stoppedVMs), status: 'neutral' },
		{ label: 'Clusters', value: String($totalClusters), status: 'info' },
		{ label: 'Total Hosts', value: String($totalHosts), status: 'info' },
		{ label: 'Connected Hosts', value: String($connectedHosts), status: 'success' },
		{ label: 'Disconnected Hosts', value: String($disconnectedCount), status: $disconnectedCount > 0 ? 'warning' : 'neutral' }
	]);
</script>

<svelte:head>
	<title>{$environmentName} - Overview</title>
</svelte:head>

<ViewLoader loading={$loading} error={$error} skeleton="overview">
	<div class="overview">
		<div class="page-header">
			<h1>Overview</h1>
			<p class="subtitle">Your infrastructure at a glance</p>
		</div>
		
		<div class="stats-grid">
			{#each stats as stat}
				<div class="stat-card" data-status={stat.status}>
					<div class="stat-label">{stat.label}</div>
					<div class="stat-value">{stat.value}</div>
				</div>
			{/each}
		</div>
		
		<div class="section">
			<h2>Quick Actions</h2>
			<div class="actions">
				<Button variant="primary">Create VM</Button>
			</div>
		</div>
	</div>
</ViewLoader>

<style>
	.overview {
		max-width: 1400px;
		margin: 0 auto;
	}

	.page-header {
		margin-bottom: 0;
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

	.stat-card[data-status="success"] {
		border-left: 3px solid var(--success);
	}

	.stat-card[data-status="info"] {
		border-left: 3px solid var(--info);
	}

	.stat-card[data-status="neutral"] {
		border-left: 3px solid var(--text-tertiary);
	}

	.stat-card[data-status="warning"] {
		border-left: 3px solid var(--warning);
	}

	.stat-label {
		color: var(--text-secondary);
		font-size: 0.875rem;
		margin-bottom: 0.5rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.stat-value {
		color: var(--text-primary);
		font-size: 2rem;
		font-weight: 700;
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

	.actions {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.activity-placeholder {
		background-color: var(--bg-tertiary);
		padding: 3rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		text-align: center;
		color: var(--text-secondary);
	}

	.activity-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.activity-item {
		display: flex;
		gap: 1rem;
		padding: 1rem;
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-color);
		transition: background-color var(--transition-fast);
	}

	.activity-item:hover {
		background-color: var(--bg-primary);
	}

	.activity-icon {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.activity-content {
		flex: 1;
		min-width: 0;
	}

	.activity-message {
		margin: 0 0 0.25rem 0;
		color: var(--text-primary);
		font-size: 0.875rem;
	}

	.activity-time {
		margin: 0;
		color: var(--text-tertiary);
		font-size: 0.75rem;
	}
</style>
