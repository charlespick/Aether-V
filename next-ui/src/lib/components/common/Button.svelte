<script lang="ts">
	interface ButtonProps {
		variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
		size?: 'sm' | 'md' | 'lg';
		disabled?: boolean;
		onclick?: () => void;
		children?: any;
	}

	let {
		variant = 'primary',
		size = 'md',
		disabled = false,
		onclick,
		children
	}: ButtonProps = $props();
</script>

<button
	class="button"
	class:primary={variant === 'primary'}
	class:secondary={variant === 'secondary'}
	class:danger={variant === 'danger'}
	class:ghost={variant === 'ghost'}
	class:sm={size === 'sm'}
	class:md={size === 'md'}
	class:lg={size === 'lg'}
	{disabled}
	{onclick}
>
	{@render children?.()}
</button>

<style>
	.button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		font-weight: 500;
		border-radius: var(--radius-md);
		transition: all var(--transition-fast);
		cursor: pointer;
		white-space: nowrap;
	}

	.button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	/* Sizes */
	.button.sm {
		padding: 0.375rem 0.75rem;
		font-size: 0.875rem;
	}

	.button.md {
		padding: 0.625rem 1.25rem;
		font-size: 0.875rem;
	}

	.button.lg {
		padding: 0.75rem 1.5rem;
		font-size: 1rem;
	}

	/* Variants */
	.button.primary {
		background-color: var(--accent-primary);
		color: white;
	}

	.button.primary:hover:not(:disabled) {
		background-color: var(--accent-hover);
		box-shadow: var(--shadow-sm);
	}

	.button.secondary {
		background-color: var(--bg-tertiary);
		color: var(--text-primary);
		border: 1px solid var(--border-color);
	}

	.button.secondary:hover:not(:disabled) {
		background-color: var(--bg-hover);
		border-color: var(--accent-primary);
	}

	.button.danger {
		background-color: var(--error);
		color: white;
	}

	.button.danger:hover:not(:disabled) {
		background-color: var(--error-hover);
		box-shadow: var(--shadow-sm);
	}

	.button.ghost {
		background-color: transparent;
		color: var(--text-secondary);
	}

	.button.ghost:hover:not(:disabled) {
		background-color: var(--bg-hover);
		color: var(--text-primary);
	}
</style>
