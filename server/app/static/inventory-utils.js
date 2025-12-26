// Shared inventory data loader for legacy UI scripts
async function fetchInventoryData() {
    const [clustersResponse, hostsResponse, vmsResponse, statsResponse] = await Promise.all([
        fetch('/api/v1/clusters', { credentials: 'same-origin' }),
        fetch('/api/v1/hosts', { credentials: 'same-origin' }),
        fetch('/api/v1/virtualmachines', { credentials: 'same-origin' }),
        fetch('/api/v1/statistics', { credentials: 'same-origin' })
    ]);

    const unauthorized = [clustersResponse, hostsResponse, vmsResponse, statsResponse].find(
        resp => resp.status === 401
    );

    if (unauthorized) {
        const error = new Error('Authentication required');
        error.status = 401;
        throw error;
    }

    const responses = [clustersResponse, hostsResponse, vmsResponse, statsResponse];
    const firstFailure = responses.find(resp => !resp.ok);
    if (firstFailure) {
        const error = new Error(`HTTP error! status: ${firstFailure.status}`);
        error.status = firstFailure.status;
        throw error;
    }

    const [clusters, hosts, vms, stats] = await Promise.all(responses.map(resp => resp.json()));

    const connectedHosts = (hosts || []).filter(host => host.connected);
    const disconnectedHosts = (hosts || []).filter(host => !host.connected);

    return {
        clusters: clusters || [],
        hosts: connectedHosts,
        vms: vms || [],
        disconnected_hosts: disconnectedHosts,
        total_hosts: (stats && stats.total_hosts) || hosts.length || 0,
        total_vms: (stats && stats.total_vms) || (vms || []).length || 0,
        total_clusters: (stats && stats.total_clusters) || (clusters || []).length || 0,
        disconnected_count: (stats && stats.disconnected_count) || disconnectedHosts.length || 0,
        last_refresh: stats ? stats.last_refresh : null,
        environment_name: stats ? stats.environment_name : 'Production Environment'
    };
}

window.fetchInventoryData = fetchInventoryData;
