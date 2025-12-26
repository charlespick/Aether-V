<script lang="ts">
	import { page } from '$app/stores';
	import HostView from '$lib/views/host/HostView.svelte';
	
	let hostname = $derived($page.params.hostname);
</script>

<HostView {hostname} />
