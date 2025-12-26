<script lang="ts">
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import ViewLoader from '$lib/components/ViewLoader.svelte';
	import Icon from '$lib/components/common/Icon.svelte';
	import { useAsyncData } from '$lib/composables/useAsyncData';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	import { formatHostname } from '$lib/utils/vm';

	const environmentName = inventoryStore.environmentName;

	interface Props {
		hostname: string;
	}

	let { hostname }: Props = $props();

	interface HostDetails {
		id: string;
		name: string;
		status: 'online' | 'offline' | 'degraded';
		cpuCores: number;
		cpuUsage: number;
		memoryTotal: number;
		memoryUsed: number;
		storageTotal: number;
		storageUsed: number;
		vmCount: number;
		uptime: number;
		version: string;
	}

	interface HostVM {
		id: string;
		name: string;
		state: string;
		cpuUsage: number;
		memoryMB: number;
	}

	interface HostData {
		details: HostDetails;
		vms: HostVM[];
	}

	// Fetch host data from shared inventory store with view-specific enrichment
	const hostData = useAsyncData<HostData>(
		async () => {
			const inventory = inventoryStore.getData();
			
			if (!inventory) {
				throw new Error('Inventory data not available');
			}
			
			const host = inventory.hosts.find(h => h.hostname === hostname);
			
			if (!host) {
				throw new Error(`Host ${hostname} not found`);
			}
			
			const hostVMs = inventory.vms.filter(vm => vm.host === hostname);
			
			return {
				details: {
					id: host.hostname,
					name: host.hostname,
					status: host.connected ? 'online' : 'offline',
					cpuCores: host.total_cpu_cores || 0,
					cpuUsage: 0, // Would need separate metrics endpoint
					memoryTotal: host.total_memory_gb || 0,
					memoryUsed: 0, // Would need separate metrics endpoint
					storageTotal: 0,
					storageUsed: 0,
					vmCount: hostVMs.length,
					uptime: 0,
					version: host.version || 'Unknown'
				},
				vms: hostVMs.map(vm => ({
					id: vm.id,
					name: vm.name,
					state: vm.state,
					cpuUsage: 0,
					memoryMB: 0
				}))
			};
		},
		{
			cache: false, // Inventory store handles caching
			refetchOnMount: true
		}
	);

	// Re-fetch data when hostname changes
	$effect(() => {
		hostname; // Track hostname dependency
		hostData.execute();
	});

	const details = $derived($hostData.data?.details);
	const displayHostname = $derived(details ? formatHostname(details.name) : '');
	
	const statusBadgeClass = $derived(() => {
		if (!details) return 'status-unknown';
		switch (details.status) {
			case 'online': return 'status-success';
			case 'offline': return 'status-off';
			case 'degraded': return 'status-warning';
			default: return 'status-unknown';
		}
	});
</script>

<svelte:head>
	<title>{$environmentName} - {displayHostname || hostname}</title>
</svelte:head>

<ViewLoader loading={$hostData.loading} error={$hostData.error} skeleton="host">
	{#if details}
		<div class="view-container">
			<div class="host-header">
			<div class="host-title-group">
				<h1 class="page-title">{displayHostname}</h1>
				<span class="status {statusBadgeClass()}">{details.status === 'online' ? 'Online' : details.status === 'offline' ? 'Offline' : 'Degraded'}</span>
			</div>
			<div class="host-actions">
				<button
					type="button"
					class="host-action-btn"
					data-tooltip="Pause"
					aria-label="Pause host"
				>
					<Icon name="pause_circle" size={22} />
				</button>
				<button
					type="button"
					class="host-action-btn"
					data-tooltip="Restart"
					aria-label="Restart host"
				>
					<Icon name="restart_alt" size={22} />
				</button>
				<button
					type="button"
					class="host-action-btn"
					data-tooltip="Shut Down"
					aria-label="Shut down host"
				>
					<Icon name="power_settings_new" size={22} />
				</button>
			</div>
		</div>			<p class="subtitle">Hyper-V Host • Version {details.version}</p>
			
			<div class="info-grid">
				<div class="info-card">
					<div class="info-label">CPU Cores</div>
					<div class="info-value">{details.cpuCores}</div>
				</div>
				<div class="info-card">
					<div class="info-label">CPU Usage</div>
					<div class="info-value">{details.cpuUsage}%</div>
				</div>
				<div class="info-card">
					<div class="info-label">Memory</div>
					<div class="info-value">{details.memoryUsed} / {details.memoryTotal} GB</div>
				</div>
				<div class="info-card">
					<div class="info-label">Storage</div>
					<div class="info-value">{details.storageUsed} / {details.storageTotal} GB</div>
				</div>
				<div class="info-card">
					<div class="info-label">Virtual Machines</div>
					<div class="info-value">{details.vmCount}</div>
				</div>
				<div class="info-card">
					<div class="info-label">Uptime</div>
					<div class="info-value">{Math.floor(details.uptime / 86400)} days</div>
				</div>
			</div>
			
			<div class="section">
				<h2>Virtual Machines</h2>
				{#if $hostData.data?.vms && $hostData.data.vms.length > 0}
					<div class="vm-table">
						<div class="table-header">
							<div>Name</div>
							<div>State</div>
							<div>CPU Usage</div>
							<div>Memory</div>
						</div>
						{#each $hostData.data.vms as vm}
							<button
								type="button"
								class="table-row"
								onclick={() => goto(`${base}/virtual-machine/${encodeURIComponent(vm.id)}`)}
							>
								<div class="vm-name">{vm.name}</div>
								<div class="vm-state" data-state={vm.state.toLowerCase()}>
									{vm.state}
								</div>
								<div>{vm.cpuUsage}%</div>
								<div>{vm.memoryMB} MB</div>
							</button>
						{/each}
					</div>
				{:else}
					<div class="placeholder">
						<p>No virtual machines found on this host</p>
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

	/* Host Header */
	.host-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0;
		gap: 1.5rem;
	}

	.host-title-group {
		display: flex;
		align-items: baseline;
		gap: 1rem;
	}

	.page-title {
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

	.host-actions {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.host-action-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		padding: 0;
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
		background: var(--bg-secondary);
		color: var(--text-primary);
		cursor: pointer;
		transition: all 0.2s ease;
		position: relative;
	}

	.host-action-btn:hover:not(:disabled) {
		background: var(--bg-tertiary);
		border-color: var(--border-color-hover);
		transform: translateY(-1px);
	}

	.host-action-btn:active:not(:disabled) {
		transform: translateY(0);
	}

	.host-action-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
		pointer-events: none;
	}

	/* Tooltip on hover */
	.host-action-btn::after {
		content: attr(data-tooltip);
		position: absolute;
		bottom: -2rem;
		left: 50%;
		transform: translateX(-50%);
		padding: 0.25rem 0.5rem;
		background: var(--bg-tooltip, rgba(0, 0, 0, 0.9));
		color: white;
		border-radius: var(--radius-sm);
		font-size: 0.75rem;
		white-space: nowrap;
		opacity: 0;
		pointer-events: none;
		transition: opacity 0.2s ease;
		z-index: 1000;
	}

	.host-action-btn:hover::after:not(:disabled) {
		opacity: 1;
	}

	.status {
		display: inline-block;
		padding: 0.375rem 0.875rem;
		border-radius: var(--radius-full, 9999px);
		font-size: 0.875rem;
		font-weight: 600;
		white-space: nowrap;
		vertical-align: baseline;
		line-height: 1;
		transform: translateY(-0.375rem);
	}

	.status-success {
		background: var(--success);
		color: white;
	}

	.status-off {
		background: var(--text-tertiary);
		color: white;
	}

	.status-warning {
		background: var(--warning);
		color: white;
	}

	.status-unknown {
		background: var(--bg-tertiary);
		color: var(--text-secondary);
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 1rem;
		margin-bottom: 2rem;
	}

	.info-card {
		background-color: var(--bg-tertiary);
		padding: 1rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-color);
	}

	.info-label {
		color: var(--text-secondary);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		margin-bottom: 0.5rem;
	}

	.info-value {
		color: var(--text-primary);
		font-size: 1.25rem;
		font-weight: 600;
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

	.vm-table {
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		overflow: hidden;
	}

	.table-header {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr 1fr;
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
		grid-template-columns: 2fr 1fr 1fr 1fr;
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
		font-weight: 500;
	}

	.vm-state[data-state='running'] {
		color: var(--success);
	}

	.vm-state[data-state='stopped'],
	.vm-state[data-state='off'] {
		color: var(--text-secondary);
	}

	.placeholder {
		background-color: var(--bg-tertiary);
		padding: 3rem;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		text-align: center;
		color: var(--text-secondary);
	}
</style>
