<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		align?: 'left' | 'right' | 'center' | 'between';
		children: Snippet;
	}

	let { align = 'right', children }: Props = $props();
</script>

<div class="form-actions" class:left={align === 'left'} class:right={align === 'right'} class:center={align === 'center'} class:between={align === 'between'}>
	{@render children()}
</div>

<style>
	.form-actions {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding-top: 1rem;
		margin-top: 1rem;
		border-top: 1px solid var(--border-color);
	}

	.form-actions.left {
		justify-content: flex-start;
	}

	.form-actions.right {
		justify-content: flex-end;
	}

	.form-actions.center {
		justify-content: center;
	}

	.form-actions.between {
		justify-content: space-between;
	}
</style>
