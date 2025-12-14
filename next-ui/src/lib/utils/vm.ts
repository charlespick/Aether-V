/**
 * VM Utility Functions
 * Helper functions for VM data formatting and state management
 */

import type { VM } from '$lib/stores/inventoryStore';

export interface VmStateMeta {
	label: string;
	badgeClass: string;
	icon: string;
	color: string;
}

/**
 * Get state metadata for a VM state
 */
export function getVmStateMeta(state: string): VmStateMeta {
	const normalized = state.toLowerCase();

	const stateMap: Record<string, VmStateMeta> = {
		'running': {
			label: 'Running',
			badgeClass: 'status-success',
			icon: 'play_circle',
			color: 'var(--success)'
		},
		'off': {
			label: 'Off',
			badgeClass: 'status-off',
			icon: 'power_settings_new',
			color: 'var(--text-tertiary)'
		},
		'saved': {
			label: 'Saved',
			badgeClass: 'status-warning',
			icon: 'pause_circle',
			color: 'var(--warning)'
		},
		'paused': {
			label: 'Paused',
			badgeClass: 'status-warning',
			icon: 'pause_circle',
			color: 'var(--warning)'
		},
		'starting': {
			label: 'Starting',
			badgeClass: 'status-info',
			icon: 'hourglass_top',
			color: 'var(--info)'
		},
		'stopping': {
			label: 'Stopping',
			badgeClass: 'status-info',
			icon: 'hourglass_top',
			color: 'var(--info)'
		},
		'deleting': {
			label: 'Deleting',
			badgeClass: 'status-danger',
			icon: 'delete',
			color: 'var(--danger)'
		}
	};

	return stateMap[normalized] || {
		label: state,
		badgeClass: 'status-unknown',
		icon: 'help',
		color: 'var(--text-tertiary)'
	};
}

/**
 * Format memory amount in GB
 */
export function formatMemoryAmount(memoryGb: number | undefined | null): string {
	if (typeof memoryGb === 'undefined' || memoryGb === null) {
		return '—';
	}

	const value = Number(memoryGb);
	if (!Number.isFinite(value)) {
		return '—';
	}

	if (value >= 1) {
		return `${value.toFixed(2)} GB`;
	}

	// Convert to MB for values less than 1 GB
	const mb = value * 1024;
	return `${Math.round(mb)} MB`;
}

/**
 * Format memory with dynamic indicator
 */
export function formatMemory(memoryGb: number | undefined | null, isDynamic: boolean = false): string {
	const formatted = formatMemoryAmount(memoryGb);
	if (formatted === '—') {
		return '—';
	}

	if (isDynamic) {
		return `${formatted} (dynamic)`;
	}

	return formatted;
}

/**
 * Resolve VM memory value (handles different field names)
 */
export function resolveVmMemoryValue(vm: VM): number | undefined {
	// Try memory_gb first (preferred)
	if (typeof vm.memory_gb !== 'undefined' && vm.memory_gb !== null) {
		return vm.memory_gb;
	}

	// Fallback to memory_mb converted to GB
	if (typeof vm.memory_mb !== 'undefined' && vm.memory_mb !== null) {
		return vm.memory_mb / 1024;
	}

	// Try memory_startup_gb for dynamic memory VMs
	if (typeof vm.memory_startup_gb !== 'undefined' && vm.memory_startup_gb !== null) {
		return vm.memory_startup_gb;
	}

	return undefined;
}

/**
 * Format operating system display name
 */
export function formatOsFamily(vm: VM): string {
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

	return vm.os_family || 'Unknown';
}

/**
 * Format hostname (short name without domain)
 */
export function formatHostname(hostname: string | undefined): string {
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

/**
 * Extract IP addresses from VM
 */
export function extractIpAddresses(vm: VM): string {
	if (Array.isArray(vm.ip_addresses) && vm.ip_addresses.length > 0) {
		return vm.ip_addresses.join(', ');
	}
	return 'Not available';
}

/**
 * Extract IP addresses from network adapter
 */
export function extractAdapterAddresses(adapter: any): string {
        if (!adapter) {
                return '—';
        }
        if (Array.isArray(adapter.ip_addresses) && adapter.ip_addresses.length > 0) {
                return adapter.ip_addresses.join(', ');
        }
        return '—';
}

/**
 * Format boolean settings with enterprise-friendly labels
 */
export function formatBooleanSetting(value: boolean | undefined | null, fallback = '—'): string {
        if (typeof value === 'undefined' || value === null) {
                return fallback;
        }
        return value ? 'Enabled' : 'Disabled';
}

/**
 * Format bandwidth range if present
 */
export function formatBandwidthRange(min?: number | null, max?: number | null): string {
        const parts: string[] = [];

        if (typeof min !== 'undefined' && min !== null) {
                parts.push(`Min ${min} Mbps`);
        }

        if (typeof max !== 'undefined' && max !== null) {
                parts.push(`Max ${max} Mbps`);
        }

        if (parts.length === 0) {
                return '—';
        }

        return parts.join(' · ');
}

/**
 * Format disk capacity
 */
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

/**
 * Format date
 */
export function formatDate(value: string | undefined | null): string {
	if (!value) {
		return 'Not available';
	}
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return 'Not available';
	}
	return date.toLocaleString();
}

/**
 * Get notes content from VM
 */
export function getNotesContent(vm: VM): string {
	if (Array.isArray(vm.notes) && vm.notes.length > 0) {
		return vm.notes.join('\n');
	}
	if (typeof vm.notes === 'string' && vm.notes.trim().length > 0) {
		return vm.notes;
	}
	return 'No notes have been recorded for this virtual machine.';
}

/**
 * Format generic value with fallback
 */
export function formatValue(value: any, fallback: string = '—'): string {
	if (value === null || typeof value === 'undefined') {
		return fallback;
	}
	const text = String(value).trim();
	return text.length > 0 ? text : fallback;
}

/**
 * Determine which VM actions are available based on state
 */
export interface VmActionAvailability {
	edit: boolean;
	start: boolean;
	shutdown: boolean;
	stop: boolean;
	reset: boolean;
	delete: boolean;
}

export function getActionAvailability(state: string, actionInProgress: boolean = false): VmActionAvailability {
	const normalized = state.toLowerCase();

	const availability: VmActionAvailability = {
		edit: true,
		start: false,
		shutdown: false,
		stop: false,
		reset: false,
		delete: false
	};

	if (actionInProgress) {
		availability.edit = false;
		return availability;
	}

	if (normalized === 'running') {
		availability.shutdown = true;
		availability.stop = true;
		availability.reset = true;
	} else if (normalized === 'off') {
		availability.start = true;
		availability.delete = true;
	} else if (normalized === 'paused' || normalized === 'saved') {
		availability.start = true;
		availability.stop = true;
		availability.delete = true;
	} else if (normalized === 'deleting') {
		// Prevent any actions while deletion is pending
		Object.keys(availability).forEach(key => {
			availability[key as keyof VmActionAvailability] = false;
		});
	}

	return availability;
}

/**
 * Get action label for display
 */
export function getActionLabel(action: string): string {
	const labels: Record<string, string> = {
		start: 'start',
		shutdown: 'shut down',
		stop: 'stop',
		reset: 'reset',
		delete: 'delete'
	};
	return labels[action] || action || 'perform';
}

/**
 * Estimate next VM state after action
 */
export function estimateNextState(action: string): string {
	switch (action) {
		case 'start':
		case 'reset':
			return 'Starting';
		case 'shutdown':
		case 'stop':
			return 'Stopping';
		case 'delete':
			return 'Deleting';
		default:
			return 'Unknown';
	}
}

/**
 * Get confirmation copy for destructive actions
 */
export interface ConfirmationCopy {
	title: string;
	message: string;
	confirmLabel: string;
}

export function getActionConfirmationCopy(action: string, vmName: string): ConfirmationCopy {
	const normalized = action.toLowerCase();

	if (normalized === 'shutdown') {
		return {
			title: 'Confirm shut down',
			message: `Shut down ${vmName}? This requests a graceful shutdown from the guest operating system.`,
			confirmLabel: 'Shut down'
		};
	}

	if (normalized === 'stop') {
		return {
			title: 'Confirm turn off',
			message: `Turn off ${vmName}? This immediately powers off the VM and may cause data loss.`,
			confirmLabel: 'Turn off'
		};
	}

	if (normalized === 'reset') {
		return {
			title: 'Confirm reset',
			message: `Reset ${vmName}? This power cycles the VM and will interrupt any running processes.`,
			confirmLabel: 'Reset'
		};
	}

	if (normalized === 'delete') {
		return {
			title: 'Confirm delete',
			message: `Delete ${vmName}? This permanently removes the VM registration and disks from the host.`,
			confirmLabel: 'Delete'
		};
	}

	return {
		title: 'Confirm action',
		message: `Proceed with ${normalized || 'this'} action on ${vmName}?`,
		confirmLabel: 'Confirm'
	};
}

/**
 * Build memory hardware items for dynamic memory VMs
 */
export function buildMemoryHardwareItems(vm: VM): Array<{ label: string; value: string }> {
	const items: Array<{ label: string; value: string }> = [];
	const resolvedMemory = resolveVmMemoryValue(vm);
	const isDynamic = vm.dynamic_memory_enabled === true;

        items.push({
                label: 'Memory',
                value: formatMemory(resolvedMemory, isDynamic)
        });

        if (isDynamic) {
                if (typeof vm.memory_startup_gb !== 'undefined') {
                        items.push({
                                label: 'Startup Memory',
                                value: formatMemoryAmount(vm.memory_startup_gb)
                        });
                }
                if (typeof vm.memory_min_gb !== 'undefined') {
                        items.push({
                                label: 'Minimum Memory',
                                value: formatMemoryAmount(vm.memory_min_gb)
                        });
                }
                if (typeof vm.memory_max_gb !== 'undefined') {
                        items.push({
                                label: 'Maximum Memory',
                                value: formatMemoryAmount(vm.memory_max_gb)
                        });
                }
                if (typeof vm.dynamic_memory_buffer !== 'undefined') {
                        items.push({
                                label: 'Dynamic Memory Buffer',
                                value: `${vm.dynamic_memory_buffer}%`
                        });
                }
        }

        return items;
}
