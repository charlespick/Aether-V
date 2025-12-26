export function formatMemoryAmount(memoryGb: number | null | undefined): string {
    if (memoryGb === null || memoryGb === undefined || typeof memoryGb !== 'number') {
        return '—';
    }

    if (!Number.isFinite(memoryGb)) {
        return '—';
    }

    return `${memoryGb.toFixed(2)} GB`;
}

export function resolveVmMemoryValue(vm: any): number | null {
    // Priority order for memory value resolution
    if (typeof vm.memory_gb !== 'undefined' && vm.memory_gb !== null) {
        return vm.memory_gb;
    }

    if (typeof vm.memory_startup_gb !== 'undefined' && vm.memory_startup_gb !== null) {
        return vm.memory_startup_gb;
    }

    if (typeof vm.memory_mb !== 'undefined' && vm.memory_mb !== null) {
        return vm.memory_mb / 1024;
    }

    return null;
}

export function formatDiskCapacity(disk: any): string {
    if (disk && typeof disk.capacity !== 'undefined') {
        return `${disk.capacity}`;
    }
    if (disk && typeof disk.size_gb !== 'undefined') {
        const size = Number(disk.size_gb);
        return Number.isFinite(size) ? `${size.toFixed(2)} GB` : `${disk.size_gb}`;
    }
    if (disk && typeof disk.size !== 'undefined') {
        return `${disk.size}`;
    }
    return '—';
}

export function formatHostname(hostname: string | null | undefined): string {
    if (!hostname) {
        return 'Unknown host';
    }
    const hostText = String(hostname).trim();
    if (!hostText) {
        return 'Unknown host';
    }
    const dotIndex = hostText.indexOf('.');
    return dotIndex === -1 ? hostText : hostText.slice(0, dotIndex);
}

export function formatDate(value: string | null | undefined): string {
    if (!value) {
        return 'Not available';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 'Not available';
    }
    return date.toLocaleString();
}

export function formatValue(value: any, fallback = '—'): string {
    if (value === null || typeof value === 'undefined') {
        return fallback;
    }
    const text = String(value).trim();
    return text.length > 0 ? text : fallback;
}

export function extractIpAddresses(vm: any): string {
    if (Array.isArray(vm.ip_addresses) && vm.ip_addresses.length > 0) {
        return vm.ip_addresses.join(', ');
    }
    return 'Not available';
}

export function extractAdapterAddresses(adapter: any): string {
    if (!adapter) {
        return '—';
    }
    if (Array.isArray(adapter.ip_addresses) && adapter.ip_addresses.length > 0) {
        return adapter.ip_addresses.join(', ');
    }
    return '—';
}

export function getNotesContent(vm: any): string {
    if (Array.isArray(vm.notes) && vm.notes.length > 0) {
        return vm.notes.join('\n');
    }
    if (typeof vm.notes === 'string' && vm.notes.trim().length > 0) {
        return vm.notes;
    }
    return 'No notes have been recorded for this virtual machine.';
}

export function formatOsFamily(vm: any): string {
    if (vm.os_name) {
        return vm.os_name;
    }

    if (!vm.os_family) {
        return 'Unknown';
    }

    const family = String(vm.os_family).toLowerCase();
    if (family.includes('windows')) {
        return 'Windows';
    }
    if (family.includes('linux')) {
        return 'Linux';
    }
    return formatValue(vm.os_family, 'Unknown');
}
