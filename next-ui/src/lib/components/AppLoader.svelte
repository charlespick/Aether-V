<script lang="ts">
	import { appLoading } from '$lib/stores/loading';

	interface Props {
		/** Show detailed progress information */
		showProgress?: boolean;
	}

	let { showProgress = true }: Props = $props();

	// Subscribe to derived stores
	const phase = appLoading.phase;
	const progress = appLoading.progress;
	const message = appLoading.message;
	const error = appLoading.error;
	const hasError = appLoading.hasError;
</script>

<!-- Fullscreen loading overlay -->
<div class="loading-overlay" role="status" aria-live="polite">
	<div class="loading-content">
		{#if $hasError}
			<!-- Error state -->
			<div class="error-container">
				<div class="error-icon">⚠️</div>
				<h2 class="error-title">Initialization Failed</h2>
				<p class="error-message">{$error || 'An unexpected error occurred'}</p>
				<button class="retry-button" onclick={() => appLoading.retry()}>
					Retry
				</button>
			</div>
		{:else}
			<!-- Loading state -->
			<div class="spinner-container">
				<!-- Circular spinner -->
				<div class="spinner">
					<svg class="spinner-svg" viewBox="0 0 50 50">
						<circle
							class="spinner-track"
							cx="25"
							cy="25"
							r="20"
							fill="none"
							stroke-width="4"
						></circle>
						<circle
							class="spinner-progress"
							cx="25"
							cy="25"
							r="20"
							fill="none"
							stroke-width="4"
							stroke-dasharray="125.6"
							stroke-dashoffset={125.6 - (125.6 * $progress) / 100}
							style="transition: stroke-dashoffset 0.3s ease"
						></circle>
					</svg>
				</div>

				{#if showProgress}
					<!-- Progress information -->
					<div class="progress-info">
						<p class="progress-message">{$message}</p>
						<p class="progress-percent">{Math.round($progress)}%</p>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.loading-overlay {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		bottom: 0;
		background: var(--bg-primary);
		z-index: 9999;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.loading-content {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.5rem;
	}

	/* Spinner styles */
	.spinner-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.5rem;
	}

	.spinner {
		width: 80px;
		height: 80px;
	}

	.spinner-svg {
		width: 100%;
		height: 100%;
		animation: rotate 2s linear infinite;
		transform-origin: center;
	}

	@keyframes rotate {
		to {
			transform: rotate(360deg);
		}
	}

	.spinner-track {
		stroke: var(--border-color);
		opacity: 0.3;
	}

	.spinner-progress {
		stroke: var(--accent-color);
		stroke-linecap: round;
		transform: rotate(-90deg);
		transform-origin: center;
	}

	/* Progress info */
	.progress-info {
		text-align: center;
		min-width: 200px;
	}

	.progress-message {
		color: var(--text-secondary);
		font-size: 0.875rem;
		margin: 0 0 0.5rem 0;
	}

	.progress-percent {
		color: var(--text-primary);
		font-size: 1.25rem;
		font-weight: 600;
		margin: 0;
		font-variant-numeric: tabular-nums;
	}

	/* Error state */
	.error-container {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		max-width: 400px;
		text-align: center;
		padding: 2rem;
	}

	.error-icon {
		font-size: 3rem;
		margin-bottom: 0.5rem;
	}

	.error-title {
		color: var(--text-primary);
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0;
	}

	.error-message {
		color: var(--text-secondary);
		font-size: 0.875rem;
		margin: 0;
		line-height: 1.5;
	}

	.retry-button {
		margin-top: 1rem;
		padding: 0.75rem 2rem;
		background: var(--accent-color);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		transition: opacity 0.2s;
	}

	.retry-button:hover {
		opacity: 0.9;
	}

	.retry-button:active {
		transform: translateY(1px);
	}
</style>
