<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label?: string;
		description?: string;
		required?: boolean;
		error?: string;
		hint?: string;
		children: Snippet;
	}

	let { label, description, required = false, error, hint, children }: Props = $props();
</script>

<div class="form-field">
	{#if label || required}
		<div class="field-header">
			{#if label}
				<label class="field-label">
					{label}
				</label>
			{/if}
			{#if required}
				<span class="field-required-pill">Required</span>
			{/if}
		</div>
	{/if}

	{#if description}
		<p class="field-description">{description}</p>
	{/if}

	<div class="field-control" class:error={!!error}>
		{@render children()}
	</div>

	{#if error}
		<p class="field-error">{error}</p>
	{:else if hint}
		<p class="field-hint">{hint}</p>
	{/if}
</div>

<style>
	.form-field {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.field-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.field-label {
		font-size: 0.875rem;
		font-weight: 500;
		color: var(--text-primary);
	}

	.field-required-pill {
		padding: 0.125rem 0.625rem;
		border-radius: 999px;
		background: rgba(148, 163, 184, 0.15);
		font-size: 0.6875rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.025em;
		color: var(--text-secondary);
	}

	.field-description {
		font-size: 0.8125rem;
		color: var(--text-secondary);
		margin: 0;
		line-height: 1.4;
	}

	.field-control {
		position: relative;
	}

	.field-control :global(input),
	.field-control :global(select),
	.field-control :global(textarea) {
		width: 100%;
		padding: 0.625rem 0.75rem;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-color);
		background: var(--bg-tertiary);
		color: var(--text-primary);
		font-size: 0.875rem;
		transition: all 0.2s;
	}

	.field-control :global(input:focus),
	.field-control :global(select:focus),
	.field-control :global(textarea:focus) {
		outline: none;
		border-color: var(--accent-primary);
		box-shadow: 0 0 0 3px rgba(74, 158, 255, 0.15);
	}

	.field-control :global(input:disabled),
	.field-control :global(select:disabled),
	.field-control :global(textarea:disabled) {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.field-control.error :global(input),
	.field-control.error :global(select),
	.field-control.error :global(textarea) {
		border-color: var(--error);
	}

	.field-control.error :global(input:focus),
	.field-control.error :global(select:focus),
	.field-control.error :global(textarea:focus) {
		box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.15);
	}

	.field-error {
		font-size: 0.8125rem;
		color: var(--error);
		margin: 0;
	}

	.field-hint {
		font-size: 0.8125rem;
		color: var(--text-secondary);
		margin: 0;
		font-style: italic;
	}

	.field-control :global(textarea) {
		min-height: 5rem;
		resize: vertical;
	}

	.field-control :global(input[type='checkbox']) {
		width: auto;
		cursor: pointer;
	}
</style>
