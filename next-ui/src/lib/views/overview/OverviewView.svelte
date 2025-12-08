<script lang="ts">
	import Button from '$lib/components/common/Button.svelte';
	
	// Placeholder data
	const stats = [
		{ label: 'Total VMs', value: '24', status: 'success' },
		{ label: 'Running', value: '18', status: 'success' },
		{ label: 'Stopped', value: '6', status: 'neutral' },
		{ label: 'Clusters', value: '3', status: 'info' }
	];
</script>

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
			<Button variant="secondary">Deploy Host</Button>
			<Button variant="secondary">View Jobs</Button>
		</div>
	</div>
	
	<div class="section">
		<h2>Recent Activity</h2>
		<div class="activity-placeholder">
			<p>No recent activity to display</p>
		</div>
	</div>
</div>

<style>
	.overview {
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
		color: var(--text-primary);
	}

	.subtitle {
		color: var(--text-secondary);
		margin: 0;
		font-size: 1rem;
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
		transition: transform var(--transition-fast), box-shadow var(--transition-fast);
	}

	.stat-card:hover {
		transform: translateY(-2px);
		box-shadow: var(--shadow-md);
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
</style>
