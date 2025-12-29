<script lang="ts">
	import { onMount } from 'svelte';
	import Header from '$lib/components/common/Header.svelte';
	import Sidebar from '$lib/components/common/Sidebar.svelte';
	import AppLoader from '$lib/components/AppLoader.svelte';
	import ToastContainer from '$lib/components/toast/ToastContainer.svelte';
	import { themeStore } from '$lib/stores/themeStore';
	import { appLoading } from '$lib/stores/loading';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	import '../app.css';

	let { children } = $props();
	
	// Subscribe to app loading state
	const isReady = appLoading.isReady;
	const environmentName = inventoryStore.environmentName;
	
	// Initialize app on mount
	onMount(() => {
		appLoading.initialize();
		
		// Initialize inventory store after app is loaded
		inventoryStore.initialize();
	});
</script>

<svelte:head>
	<link rel="icon" type="image/png" href="/assets/Logo.png" />
	<title>{$isReady ? $environmentName : 'Loading Aether-V'}</title>
</svelte:head>

{#if !$isReady}
	<!-- Show fullscreen loading spinner during app initialization -->
	<AppLoader />
{:else}
	<!-- Main application shell - only shown when fully initialized -->
	<div class="app">
		<Header />
		
		<div class="app-shell">
			<Sidebar />
			
			<main class="content">
				{@render children()}
			</main>
		</div>
	</div>
{/if}

<!-- Toast notifications - always rendered for connection status -->
<ToastContainer />

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
	}

	.app {
		display: flex;
		flex-direction: column;
		height: 100vh;
		background-color: var(--bg-primary);
		color: var(--text-primary);
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
		background-color: var(--bg-secondary);
	}
</style>
