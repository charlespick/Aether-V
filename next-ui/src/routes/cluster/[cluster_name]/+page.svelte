<script lang="ts">
	import { page } from '$app/stores';
	import ClusterView from '$lib/views/cluster/ClusterView.svelte';
	
	let clusterName = $derived($page.params.cluster_name);
</script>

<ClusterView {clusterName} />
