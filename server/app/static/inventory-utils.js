(function (global) {
    'use strict';

    const CLUSTER_SENTINELS = new Set([
        '',
        'default',
        'standalone',
        'stand-alone',
        'standalone host',
        'standalone-host',
        'none',
        'null',
        'n/a',
        'not clustered',
        'notclustered',
        'nonclustered',
        'single host',
        'single-host',
    ]);

    const BOOLEAN_TRUE_VALUES = new Set([
        '1',
        'true',
        'yes',
        'enabled',
        'ha',
        'clustered',
        'high availability',
        'high-availability',
        'highavailability',
        'on',
    ]);

    const BOOLEAN_FALSE_VALUES = new Set([
        '0',
        'false',
        'no',
        'disabled',
        'off',
        'standalone',
        'stand-alone',
        'not clustered',
        'notclustered',
        'nonclustered',
        'single host',
        'single-host',
    ]);

    const HA_FLAG_KEYS = [
        'high_availability',
        'highavailability',
        'ha_enabled',
        'haenabled',
        'clustered',
        'is_clustered',
        'isclustered',
        'vm_clustered',
        'vmclustered',
        'ha',
    ];

    function normalizeBoolean(value) {
        if (value === null || typeof value === 'undefined') {
            return null;
        }

        if (typeof value === 'boolean') {
            return value;
        }

        if (typeof value === 'number') {
            if (Number.isNaN(value)) {
                return null;
            }
            if (value === 1) {
                return true;
            }
            if (value === 0) {
                return false;
            }
        }

        if (typeof value === 'string') {
            const normalized = value.trim().toLowerCase();
            if (!normalized) {
                return null;
            }
            if (BOOLEAN_TRUE_VALUES.has(normalized)) {
                return true;
            }
            if (BOOLEAN_FALSE_VALUES.has(normalized)) {
                return false;
            }
        }

        return null;
    }

    function sanitizeClusterName(value) {
        if (value === null || typeof value === 'undefined') {
            return null;
        }

        const text = String(value).trim();
        if (!text) {
            return null;
        }

        if (CLUSTER_SENTINELS.has(text.toLowerCase())) {
            return null;
        }

        return text;
    }

    function buildHostIndex(hosts) {
        const index = new Map();
        if (!Array.isArray(hosts)) {
            return index;
        }

        for (const host of hosts) {
            if (host && host.hostname) {
                index.set(String(host.hostname).toLowerCase(), host);
            }
        }

        return index;
    }

    function deriveVmAvailability(vm, options = {}) {
        const record = vm || {};
        const normalizedFields = {};

        for (const [rawKey, rawValue] of Object.entries(record)) {
            if (rawKey === null || typeof rawKey === 'undefined') {
                continue;
            }
            const loweredKey = String(rawKey).toLowerCase();
            if (!(loweredKey in normalizedFields)) {
                normalizedFields[loweredKey] = rawValue;
            }
        }

        const hostIndex = options.hostIndex instanceof Map ? options.hostIndex : null;
        let host = options.host || null;
        const hostNameCandidate =
            record.host ||
            record.hostname ||
            record.hyperv_host ||
            record.hypervisor ||
            null;

        if (!host && hostIndex && hostNameCandidate) {
            host = hostIndex.get(String(hostNameCandidate).toLowerCase()) || null;
        }

        let vmCluster = null;
        const vmClusterCandidates = [
            record.cluster,
            normalizedFields['cluster'],
            normalizedFields['cluster_name'],
            normalizedFields['clustername'],
        ];
        for (const candidate of vmClusterCandidates) {
            const sanitized = sanitizeClusterName(candidate);
            if (sanitized) {
                vmCluster = sanitized;
                break;
            }
        }

        let hostCluster = null;
        if (host) {
            const hostClusterCandidates = [
                host.cluster,
                host.ClusterName,
                host.cluster_name,
            ];
            for (const candidate of hostClusterCandidates) {
                const sanitized = sanitizeClusterName(candidate);
                if (sanitized) {
                    hostCluster = sanitized;
                    break;
                }
            }
        }

        const clusterName = vmCluster || hostCluster || (
            Object.prototype.hasOwnProperty.call(options, 'cluster')
                ? sanitizeClusterName(options.cluster)
                : null
        );

        let availability = null;
        let source = 'unknown';
        for (const key of HA_FLAG_KEYS) {
            if (Object.prototype.hasOwnProperty.call(normalizedFields, key)) {
                const value = normalizedFields[key];
                const result = normalizeBoolean(value);
                if (result !== null) {
                    availability = result;
                    source = 'vm';
                    break;
                }
            }
        }

        const hostAvailable = Boolean(host || options.hostPresent);
        if (availability === null) {
            if (vmCluster) {
                availability = true;
                source = 'cluster';
            } else if (!hostCluster && hostAvailable) {
                availability = false;
                source = 'host';
            }
        }

        return {
            availability,
            isHighlyAvailable: availability === true,
            determined: availability !== null,
            clusterName,
            host,
            hostName: host ? host.hostname : hostNameCandidate,
            source,
        };
    }

    function formatVmAvailabilityLabel(vm, options = {}) {
        const info = deriveVmAvailability(vm, options);
        if (info.availability === true) {
            return info.clusterName ? `Yes (${info.clusterName})` : 'Yes';
        }
        if (info.availability === false) {
            return 'No';
        }
        return 'Unknown';
    }

    global.inventoryUtils = {
        normalizeBoolean,
        sanitizeClusterName,
        buildHostIndex,
        deriveVmAvailability,
        formatVmAvailabilityLabel,
    };
})(window);
