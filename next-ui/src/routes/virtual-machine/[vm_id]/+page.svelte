<script lang="ts">
	import { page } from '$app/stores';
	import VmView from '$lib/views/vm/VmView.svelte';
	
	let vmId = $derived($page.params.vm_id);
</script>

<VmView {vmId} />
