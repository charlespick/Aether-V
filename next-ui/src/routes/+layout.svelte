<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import Header from '$lib/components/common/Header.svelte';
	import Sidebar from '$lib/components/common/Sidebar.svelte';
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Aether-V — Next UI</title>
</svelte:head>

<div class="app">
	<Header />
	
	<div class="app-shell">
		<Sidebar />
		
		<main class="content">
			{@render children()}
		</main>
	</div>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
	}

	.app {
		display: flex;
		flex-direction: column;
		min-height: 100vh;
		background-color: var(--bg-primary, #0f0f0f);
		color: var(--text-primary, #ffffff);
	}

	.app-shell {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.content {
		flex: 1;
		padding: 2rem;
		overflow-y: auto;
		background-color: var(--bg-secondary, #1a1a1a);
	}
</style>
