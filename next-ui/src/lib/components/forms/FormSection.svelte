<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title?: string;
		description?: string;
		collapsible?: boolean;
		defaultExpanded?: boolean;
		children: Snippet;
	}

	let {
		title,
		description,
		collapsible = false,
		defaultExpanded = true,
		children
	}: Props = $props();

	let expanded = $state(defaultExpanded);
</script>

<div class="form-section">
	{#if title || description}
		<div class="section-header" class:clickable={collapsible}>
			<div class="section-info">
				{#if title}
					<h3 class="section-title">{title}</h3>
				{/if}
				{#if description}
					<p class="section-description">{description}</p>
				{/if}
			</div>

			{#if collapsible}
				<button
					type="button"
					class="section-toggle"
					onclick={() => (expanded = !expanded)}
					aria-label={expanded ? 'Collapse section' : 'Expand section'}
				>
					<svg
						width="20"
						height="20"
						viewBox="0 0 20 20"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						class:rotated={!expanded}
					>
						<path d="M6 8l4 4 4-4" />
					</svg>
				</button>
			{/if}
		</div>
	{/if}

	{#if !collapsible || expanded}
		<div class="section-content">
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.form-section {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem;
		border: 1px solid rgba(148, 163, 184, 0.2);
		border-radius: var(--radius-lg);
		background: rgba(148, 163, 184, 0.05);
	}

	.section-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.section-header.clickable {
		cursor: pointer;
	}

	.section-info {
		flex: 1;
	}

	.section-title {
		font-size: 1rem;
		font-weight: 600;
		color: var(--text-primary);
		margin: 0 0 0.25rem 0;
	}

	.section-description {
		font-size: 0.8125rem;
		color: var(--text-secondary);
		margin: 0;
		line-height: 1.4;
	}

	.section-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		border: none;
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		border-radius: var(--radius-md);
		transition: all 0.2s;
		flex-shrink: 0;
	}

	.section-toggle:hover {
		background: var(--bg-hover);
		color: var(--text-primary);
	}

	.section-toggle svg {
		transition: transform 0.2s;
	}

	.section-toggle svg.rotated {
		transform: rotate(-90deg);
	}

	.section-content {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
</style>
