export type VmState =
    | 'Running'
    | 'Off'
    | 'Saved'
    | 'Paused'
    | 'Starting'
    | 'Stopping'
    | 'Deleting'
    | 'Suspended'
    | 'Pausing'
    | 'Resuming'
    | 'FastSaved'
    | 'FastSaving'
    | 'RunningCritical'
    | 'OffCritical'
    | 'StoppingCritical'
    | 'SavedCritical'
    | 'PausedCritical'
    | 'StartingCritical'
    | 'ResetCritical'
    | 'SavingCritical'
    | 'PausingCritical'
    | 'ResumingCritical'
    | 'FastSavedCritical'
    | 'FastSavingCritical'
    | string;

export interface VmStateMeta {
    label: string;
    badgeClass: string;
}

export function getVmStateMeta(state: VmState | null | undefined): VmStateMeta {
    if (!state) {
        return { label: 'Unknown', badgeClass: 'unknown' };
    }

    const normalized = String(state).toLowerCase();

    if (normalized === 'running') {
        return { label: 'Running', badgeClass: 'running' };
    }

    if (normalized === 'off') {
        return { label: 'Off', badgeClass: 'off' };
    }

    if (normalized === 'saved' || normalized === 'fastsaved') {
        return { label: 'Saved', badgeClass: 'saved' };
    }

    if (normalized === 'paused' || normalized === 'suspended') {
        return { label: 'Paused', badgeClass: 'paused' };
    }

    if (normalized === 'starting') {
        return { label: 'Starting', badgeClass: 'transitioning' };
    }

    if (normalized === 'stopping') {
        return { label: 'Stopping', badgeClass: 'transitioning' };
    }

    if (normalized === 'deleting') {
        return { label: 'Deleting', badgeClass: 'deleting' };
    }

    if (normalized.includes('critical')) {
        return { label: state, badgeClass: 'critical' };
    }

    return { label: state, badgeClass: 'unknown' };
}

export interface ActionAvailability {
    edit: boolean;
    start: boolean;
    shutdown: boolean;
    stop: boolean;
    reset: boolean;
    delete: boolean;
}

export function getActionAvailability(
    state: VmState | null | undefined,
    actionInProgress: boolean
): ActionAvailability {
    const normalized = typeof state === 'string' ? state.toLowerCase() : String(state || '').toLowerCase();

    const availability: ActionAvailability = {
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
        Object.keys(availability).forEach((key) => {
            availability[key as keyof ActionAvailability] = false;
        });
    }

    return availability;
}

export function estimateNextState(action: string): VmState {
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

export function getDefaultSuccessMessage(action: string, vmName: string): string {
    switch (action) {
        case 'start':
            return `Start command accepted for VM ${vmName}.`;
        case 'shutdown':
            return `Shutdown command accepted for VM ${vmName}.`;
        case 'stop':
            return `Stop command accepted for VM ${vmName}.`;
        case 'reset':
            return `Reset command accepted for VM ${vmName}.`;
        case 'delete':
            return `Delete command accepted for VM ${vmName}.`;
        default:
            return `Command accepted for VM ${vmName}.`;
    }
}

export function enhanceShutdownError(errorMessage: string): string {
    if (!errorMessage) {
        return errorMessage;
    }

    const message = String(errorMessage).toLowerCase();

    // Check if this looks like a graceful shutdown failure
    if (message.includes('stop-vm') || message.includes('shutdown')) {
        if (
            message.includes('unspecified') ||
            message.includes('failed') ||
            message.includes('timeout') ||
            message.includes('not respond')
        ) {
            return `${errorMessage}\n\nNote: Graceful shutdown requires the guest OS to be responsive and have working Hyper-V Integration Services. If the VM is unresponsive, use "Turn Off" instead.`;
        }
    }

    return errorMessage;
}
