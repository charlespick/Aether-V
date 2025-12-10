<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/common/Icon.svelte';

	interface Props {
		/** Whether data is currently loading */
		loading: boolean;
		/** Error message if loading failed */
		error?: string | null;
		/** Skeleton variant to show during loading */
		skeleton?: 'overview' | 'host' | 'vm' | 'cluster' | 'list' | 'default';
		/** Minimum height for the loader area */
		minHeight?: string;
		/** Content to render when loaded */
		children: Snippet;
	}

	let {
		loading,
		error = null,
		skeleton = 'default',
		minHeight = '400px',
		children
	}: Props = $props();
</script>

<div class="view-loader" style="min-height: {minHeight}">
	{#if error}
		<!-- Error state -->
		<div class="error-state">
		<div class="error-icon">
			<Icon name="warning" size={48} />
		</div>
		<h3 class="error-title">Failed to load data</h3>
		<p class="error-message">{typeof error === 'string' ? error : JSON.stringify(error)}</p>
		</div>
	{:else if loading}
		<!-- Loading state with skeleton -->
		<div class="skeleton-container" data-skeleton={skeleton}>
			{#if skeleton === 'overview'}
				<div class="skeleton-overview">
					<!-- Stats cards row -->
					<div class="skeleton-stats">
						{#each Array(4) as _, i}
							<div class="skeleton-card">
								<div class="skeleton-line skeleton-title"></div>
								<div class="skeleton-line skeleton-value"></div>
								<div class="skeleton-line skeleton-label"></div>
							</div>
						{/each}
					</div>
					
					<!-- Charts section -->
					<div class="skeleton-charts">
						<div class="skeleton-card skeleton-chart">
							<div class="skeleton-line skeleton-title"></div>
							<div class="skeleton-chart-area"></div>
						</div>
						<div class="skeleton-card skeleton-chart">
							<div class="skeleton-line skeleton-title"></div>
							<div class="skeleton-chart-area"></div>
						</div>
					</div>
				</div>
			{:else if skeleton === 'host' || skeleton === 'cluster'}
				<div class="skeleton-detail">
					<!-- Header section -->
					<div class="skeleton-header">
						<div class="skeleton-line skeleton-title-large"></div>
						<div class="skeleton-line skeleton-subtitle"></div>
					</div>
					
					<!-- Info cards -->
					<div class="skeleton-info-grid">
						{#each Array(6) as _, i}
							<div class="skeleton-card skeleton-info-card">
								<div class="skeleton-line skeleton-label"></div>
								<div class="skeleton-line skeleton-value"></div>
							</div>
						{/each}
					</div>
					
					<!-- Table -->
					<div class="skeleton-card">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-table">
							{#each Array(5) as _, i}
								<div class="skeleton-table-row">
									<div class="skeleton-line"></div>
									<div class="skeleton-line"></div>
									<div class="skeleton-line"></div>
								</div>
							{/each}
						</div>
					</div>
				</div>
			{:else if skeleton === 'vm'}
				<div class="skeleton-detail">
					<!-- VM header with thumbnail -->
					<div class="skeleton-header">
						<div class="skeleton-thumbnail"></div>
						<div class="skeleton-header-text">
							<div class="skeleton-line skeleton-title-large"></div>
							<div class="skeleton-line skeleton-subtitle"></div>
						</div>
					</div>
					
					<!-- VM stats -->
					<div class="skeleton-stats">
						{#each Array(3) as _, i}
							<div class="skeleton-card">
								<div class="skeleton-line skeleton-label"></div>
								<div class="skeleton-line skeleton-value"></div>
							</div>
						{/each}
					</div>
					
					<!-- VM details card -->
					<div class="skeleton-card">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-detail-list">
							{#each Array(8) as _, i}
								<div class="skeleton-detail-row">
									<div class="skeleton-line skeleton-label"></div>
									<div class="skeleton-line skeleton-value"></div>
								</div>
							{/each}
						</div>
					</div>
				</div>
			{:else if skeleton === 'list'}
				<div class="skeleton-list">
					<div class="skeleton-card">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-list-items">
							{#each Array(8) as _, i}
								<div class="skeleton-list-item">
									<div class="skeleton-line"></div>
								</div>
							{/each}
						</div>
					</div>
				</div>
			{:else}
				<!-- Default skeleton -->
				<div class="skeleton-default">
					<div class="skeleton-card">
						<div class="skeleton-line skeleton-title"></div>
						<div class="skeleton-line"></div>
						<div class="skeleton-line"></div>
						<div class="skeleton-line" style="width: 60%"></div>
					</div>
				</div>
			{/if}
		</div>
	{:else}
		<!-- Content loaded successfully -->
		{@render children()}
	{/if}
</div>

<style>
	.view-loader {
		width: 100%;
		position: relative;
	}

	/* Error state */
	.error-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 4rem 2rem;
		text-align: center;
		min-height: 300px;
	}

	.error-icon {
		color: var(--error);
		margin-bottom: 1rem;
	}

	.error-title {
		color: var(--text-primary);
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0 0 0.5rem 0;
	}

	.error-message {
		color: var(--text-secondary);
		font-size: 0.875rem;
		margin: 0;
		max-width: 500px;
	}

	/* Skeleton container */
	.skeleton-container {
		animation: fadeIn 0.2s ease-in;
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	/* Common skeleton elements */
	.skeleton-line {
		background: linear-gradient(
			90deg,
			var(--skeleton-base) 0%,
			var(--skeleton-highlight) 50%,
			var(--skeleton-base) 100%
		);
		background-size: 200% 100%;
		animation: shimmer 1.5s ease-in-out infinite;
		border-radius: 4px;
		height: 1rem;
	}

	@keyframes shimmer {
		0% {
			background-position: -200% 0;
		}
		100% {
			background-position: 200% 0;
		}
	}

	.skeleton-title {
		width: 40%;
		height: 1.25rem;
		margin-bottom: 0.5rem;
	}

	.skeleton-title-large {
		width: 50%;
		height: 2rem;
		margin-bottom: 0.75rem;
	}

	.skeleton-subtitle {
		width: 30%;
		height: 1rem;
	}

	.skeleton-label {
		width: 35%;
		height: 0.875rem;
	}

	.skeleton-value {
		width: 50%;
		height: 1.5rem;
		margin-top: 0.5rem;
	}

	.skeleton-card {
		background: var(--bg-primary);
		border: 1px solid var(--border-color);
		border-radius: 8px;
		padding: 1.5rem;
	}

	/* Overview skeleton */
	.skeleton-overview {
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.skeleton-stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 1rem;
	}

	.skeleton-charts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
		gap: 1rem;
	}

	.skeleton-chart-area {
		height: 200px;
		background: linear-gradient(
			90deg,
			var(--skeleton-base) 0%,
			var(--skeleton-highlight) 50%,
			var(--skeleton-base) 100%
		);
		background-size: 200% 100%;
		animation: shimmer 1.5s ease-in-out infinite;
		border-radius: 4px;
		margin-top: 1rem;
	}

	/* Detail view skeleton (host/cluster/vm) */
	.skeleton-detail {
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.skeleton-header {
		display: flex;
		gap: 1.5rem;
		align-items: center;
	}

	.skeleton-header-text {
		flex: 1;
	}

	.skeleton-thumbnail {
		width: 80px;
		height: 80px;
		background: linear-gradient(
			90deg,
			var(--skeleton-base) 0%,
			var(--skeleton-highlight) 50%,
			var(--skeleton-base) 100%
		);
		background-size: 200% 100%;
		animation: shimmer 1.5s ease-in-out infinite;
		border-radius: 8px;
	}

	.skeleton-info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 1rem;
	}

	.skeleton-info-card {
		padding: 1rem;
	}

	.skeleton-table {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-top: 1rem;
	}

	.skeleton-table-row {
		display: grid;
		grid-template-columns: 2fr 1fr 1fr;
		gap: 1rem;
	}

	.skeleton-detail-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		margin-top: 1rem;
	}

	.skeleton-detail-row {
		display: grid;
		grid-template-columns: 1fr 2fr;
		gap: 1rem;
		align-items: center;
	}

	/* List skeleton */
	.skeleton-list-items {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-top: 1rem;
	}

	.skeleton-list-item {
		padding: 0.75rem 0;
		border-bottom: 1px solid var(--border-color);
	}

	.skeleton-list-item:last-child {
		border-bottom: none;
	}

	/* Default skeleton */
	.skeleton-default .skeleton-card {
		max-width: 800px;
	}

	.skeleton-default .skeleton-line {
		margin-bottom: 1rem;
	}

	.skeleton-default .skeleton-line:last-child {
		margin-bottom: 0;
	}

	/* CSS custom properties for theming */
	:global(:root) {
		--skeleton-base: #e0e0e0;
		--skeleton-highlight: #f5f5f5;
	}

	:global([data-theme='dark']) {
		--skeleton-base: #2a2a2a;
		--skeleton-highlight: #3a3a3a;
	}
</style>
