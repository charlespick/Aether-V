<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import FormSection from '$lib/components/forms/FormSection.svelte';
	import FormActions from '$lib/components/forms/FormActions.svelte';
	import Button from '$lib/components/common/Button.svelte';

	interface JobStep {
		key: string;
		label: string;
		jobType: string;
		status?: 'pending' | 'running' | 'completed' | 'failed';
		jobId?: string;
	}

	interface Props {
		isOpen: boolean;
		jobId: string;
		onClose: () => void;
		onViewSubJob?: (jobId: string) => void;
	}

	let { isOpen = $bindable(false), jobId, onClose, onViewSubJob }: Props = $props();

	// Job data (would be fetched from API and updated via WebSocket)
	let jobData = $state({
		id: jobId,
		type: 'managed_deployment',
		status: 'running' as 'pending' | 'running' | 'completed' | 'failed',
		vmName: 'web-server-01',
		targetHost: 'hyperv01.example.com',
		imageName: 'Windows Server 2022',
		createdAt: new Date().toISOString(),
		startedAt: new Date().toISOString(),
		completedAt: null as string | null,
		error: null as string | null,
		logs: [] as string[]
	});

	// Deployment steps (for managed deployments)
	let deploymentSteps = $state<JobStep[]>([
		{ key: 'vm', label: 'Create VM', jobType: 'create_vm', status: 'completed', jobId: 'job-001' },
		{ key: 'disk', label: 'Create Disk', jobType: 'create_disk', status: 'running', jobId: 'job-002' },
		{ key: 'nic', label: 'Create NIC', jobType: 'create_nic', status: 'pending' },
		{ key: 'init', label: 'Initialize Guest', jobType: 'initialize_vm', status: 'pending' }
	]);

	let followOutput = $state(true);

	// TODO: Implement WebSocket connection for real-time updates
	// $effect(() => {
	//   if (isOpen && jobId) {
	//     // Connect to WebSocket: ws://server/ws/jobs/{jobId}
	//     // Listen for status updates, log entries, step progress
	//     // Update jobData and deploymentSteps reactively
	//   }
	//   return () => {
	//     // Cleanup: disconnect WebSocket
	//   };
	// });

	// Copy logs to clipboard
	function copyLogs() {
		navigator.clipboard.writeText(jobData.logs.join('\n'));
		// Would show toast notification
	}

	// Get status badge class
	function getStatusClass(status: string): string {
		switch (status) {
			case 'completed':
				return 'status-success';
			case 'failed':
				return 'status-error';
			case 'running':
				return 'status-running';
			default:
				return 'status-pending';
		}
	}

	// Calculate duration
	function getDuration(): string {
		if (!jobData.startedAt) return 'Not started';
		
		const start = new Date(jobData.startedAt).getTime();
		const end = jobData.completedAt ? new Date(jobData.completedAt).getTime() : Date.now();
		const duration = Math.floor((end - start) / 1000);
		
		const minutes = Math.floor(duration / 60);
		const seconds = duration % 60;
		
		return `${minutes}m ${seconds}s`;
	}
</script>

<Modal {isOpen} {onClose} title="Job Details" variant="slideOver" width="lg">
	<div class="job-content">
		<!-- Job Header -->
		<div class="job-header">
			<div class="job-header-info">
				<h3 class="job-title">{jobData.vmName}</h3>
				<span class="job-id">Job ID: {jobData.id}</span>
			</div>
			<span class="status-badge {getStatusClass(jobData.status)}">
				{jobData.status}
			</span>
		</div>

		<!-- Job Information -->
		<FormSection title="Job Information">
			<div class="info-grid">
				<div class="info-row">
					<span class="info-label">Type</span>
					<span class="info-value">{jobData.type}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Status</span>
					<span class="info-value">{jobData.status}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Created</span>
					<span class="info-value">{new Date(jobData.createdAt).toLocaleString()}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Duration</span>
					<span class="info-value">{getDuration()}</span>
				</div>
			</div>
		</FormSection>

		<!-- Request Summary -->
		<FormSection title="Request Summary">
			<div class="info-grid">
				<div class="info-row">
					<span class="info-label">VM Name</span>
					<span class="info-value">{jobData.vmName}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Target Host</span>
					<span class="info-value">{jobData.targetHost}</span>
				</div>
				<div class="info-row">
					<span class="info-label">Image</span>
					<span class="info-value">{jobData.imageName}</span>
				</div>
			</div>
		</FormSection>

		<!-- Deployment Steps (for managed deployments) -->
		{#if jobData.type === 'managed_deployment'}
			<FormSection title="Deployment Steps">
				<div class="steps-list">
					{#each deploymentSteps as step}
						<div class="step-row">
							<div class="step-info">
								<span class="step-label">{step.label}</span>
								<span class="status-badge small {getStatusClass(step.status || 'pending')}">
									{step.status || 'pending'}
								</span>
							</div>
							{#if step.jobId}
								<Button
									variant="ghost"
									size="sm"
									onclick={() => onViewSubJob?.(step.jobId!)}
								>
									View
								</Button>
							{/if}
						</div>
					{/each}
				</div>
			</FormSection>
		{/if}

		<!-- Activity Log -->
		<FormSection title="Activity Log">
			<div class="log-controls">
				<label class="checkbox-label">
					<input type="checkbox" bind:checked={followOutput} />
					<span>Follow Output</span>
				</label>
				<Button variant="ghost" size="sm" onclick={copyLogs}>
					Copy to Clipboard
				</Button>
			</div>

			<div class="log-output">
				{#if jobData.logs.length > 0}
					<pre>{jobData.logs.join('\n')}</pre>
				{:else}
					<p class="log-empty">No log output yet...</p>
				{/if}
			</div>

			<div class="websocket-note">
				<strong>Note:</strong> This is a placeholder. WebSocket integration for real-time log streaming
				will be implemented in a future update.
			</div>
		</FormSection>

		<!-- Error Section -->
		{#if jobData.error}
			<FormSection title="Error Details">
				<div class="error-box">
					<pre>{jobData.error}</pre>
				</div>
			</FormSection>
		{/if}
	</div>

	<FormActions>
		<Button variant="secondary" onclick={onClose}>Close</Button>
	</FormActions>
</Modal>

<style>
	.job-content {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.job-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		padding: 1rem;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-color);
	}

	.job-header-info {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.job-title {
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--text-primary);
		margin: 0;
	}

	.job-id {
		font-size: 0.8125rem;
		color: var(--text-secondary);
		font-family: monospace;
	}

	.status-badge {
		padding: 0.375rem 0.875rem;
		border-radius: var(--radius-md);
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.status-badge.small {
		padding: 0.25rem 0.625rem;
		font-size: 0.6875rem;
	}

	.status-success {
		background: rgba(74, 222, 128, 0.15);
		color: var(--success);
	}

	.status-error {
		background: rgba(248, 113, 113, 0.15);
		color: var(--error);
	}

	.status-running {
		background: rgba(74, 158, 255, 0.15);
		color: var(--accent-primary);
	}

	.status-pending {
		background: rgba(148, 163, 184, 0.15);
		color: var(--text-secondary);
	}

	.info-grid {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.info-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.625rem 0.75rem;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
	}

	.info-label {
		font-size: 0.875rem;
		color: var(--text-secondary);
		font-weight: 500;
	}

	.info-value {
		font-size: 0.875rem;
		color: var(--text-primary);
		font-family: monospace;
	}

	.steps-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.step-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.75rem;
		background: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-color);
	}

	.step-info {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex: 1;
	}

	.step-label {
		font-size: 0.875rem;
		color: var(--text-primary);
		font-weight: 500;
	}

	.log-controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.5rem 0;
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		color: var(--text-primary);
	}

	.checkbox-label input[type='checkbox'] {
		margin: 0;
	}

	.log-output {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
		padding: 1rem;
		max-height: 400px;
		overflow-y: auto;
		font-family: monospace;
		font-size: 0.8125rem;
	}

	.log-output pre {
		margin: 0;
		color: var(--text-primary);
		white-space: pre-wrap;
		word-break: break-all;
	}

	.log-empty {
		color: var(--text-secondary);
		font-style: italic;
		margin: 0;
	}

	.websocket-note {
		padding: 0.75rem;
		background: rgba(74, 158, 255, 0.1);
		border: 1px solid rgba(74, 158, 255, 0.3);
		border-radius: var(--radius-md);
		font-size: 0.8125rem;
		color: var(--text-secondary);
		line-height: 1.4;
		font-style: italic;
	}

	.websocket-note strong {
		color: var(--accent-primary);
	}

	.error-box {
		padding: 1rem;
		background: rgba(248, 113, 113, 0.1);
		border: 1px solid rgba(248, 113, 113, 0.3);
		border-radius: var(--radius-md);
		font-family: monospace;
		font-size: 0.8125rem;
	}

	.error-box pre {
		margin: 0;
		color: var(--error);
		white-space: pre-wrap;
		word-break: break-all;
	}
</style>
