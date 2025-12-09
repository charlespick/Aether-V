<script lang="ts">
	interface InputProps {
		type?: 'text' | 'email' | 'password' | 'number';
		value?: string | number;
		placeholder?: string;
		label?: string;
		disabled?: boolean;
		error?: string;
	}

	let {
		type = 'text',
		value = $bindable(''),
		placeholder = '',
		label = '',
		disabled = false,
		error = ''
	}: InputProps = $props();
</script>

<div class="input-wrapper">
	{#if label}
		<label class="input-label">{label}</label>
	{/if}
	<input
		class="input"
		class:error={error}
		{type}
		{placeholder}
		{disabled}
		bind:value
	/>
	{#if error}
		<span class="error-message">{error}</span>
	{/if}
</div>

<style>
	.input-wrapper {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.input-label {
		font-size: 0.875rem;
		font-weight: 500;
		color: var(--text-primary);
	}

	.input {
		padding: 0.625rem 0.75rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: 0.875rem;
		transition: border-color var(--transition-fast);
	}

	.input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.input.error {
		border-color: var(--error);
	}

	.input:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error-message {
		font-size: 0.75rem;
		color: var(--error);
	}
</style>
