/**
 * VM Action Utilities
 * 
 * Helper functions for performing VM power actions with toast notifications.
 * These demonstrate the enhanced toast system capabilities.
 */

import { toastStore } from '$lib/stores/toastStore';

export type VMPowerAction = 'start' | 'stop' | 'restart' | 'shutdown' | 'delete';

interface VMActionResult {
    success: boolean;
    message?: string;
}

/**
 * Execute a VM power action with appropriate toast notifications.
 * 
 * @example
 * ```typescript
 * await executeVMAction('start', 'vm-123', 'WebServer-01');
 * ```
 */
export async function executeVMAction(
    action: VMPowerAction,
    vmId: string,
    vmName?: string
): Promise<VMActionResult> {
    const actionVerbs: Record<VMPowerAction, { present: string; past: string }> = {
        start: { present: 'Starting', past: 'Started' },
        stop: { present: 'Stopping', past: 'Stopped' },
        restart: { present: 'Restarting', past: 'Restarted' },
        shutdown: { present: 'Shutting down', past: 'Shut down' },
        delete: { present: 'Deleting', past: 'Deleted' }
    };

    const verb = actionVerbs[action];

    // Show "action submitted" toast
    toastStore.actionSubmitted(verb.present, 'VM', vmName);

    try {
        // Make API call to perform action
        const response = await fetch(`/api/vms/${vmId}/action`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ action })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
            throw new Error(errorData.message || `Failed to ${action} VM`);
        }

        // Show success toast
        toastStore.actionSuccess(verb.past, 'VM', vmName);

        return { success: true };
    } catch (error) {
        // Show error toast
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
        toastStore.actionFailed(action, 'VM', vmName, errorMessage);

        return {
            success: false,
            message: errorMessage
        };
    }
}

/**
 * Execute a bulk VM action on multiple VMs.
 * 
 * @example
 * ```typescript
 * await executeBulkVMAction('start', [
 *   { id: 'vm-1', name: 'Web-01' },
 *   { id: 'vm-2', name: 'Web-02' }
 * ]);
 * ```
 */
export async function executeBulkVMAction(
    action: VMPowerAction,
    vms: Array<{ id: string; name?: string }>
): Promise<{ succeeded: number; failed: number }> {
    const actionVerbs: Record<VMPowerAction, { present: string; past: string }> = {
        start: { present: 'Starting', past: 'Started' },
        stop: { present: 'Stopping', past: 'Stopped' },
        restart: { present: 'Restarting', past: 'Restarted' },
        shutdown: { present: 'Shutting down', past: 'Shut down' },
        delete: { present: 'Deleting', past: 'Deleted' }
    };

    const verb = actionVerbs[action];

    // Show initial toast for bulk action
    toastStore.info(`${verb.present} ${vms.length} VMs...`, {
        title: 'Bulk Action',
        icon: 'pending_actions',
        duration: 2000
    });

    const results = await Promise.allSettled(
        vms.map(vm => executeVMAction(action, vm.id, vm.name))
    );

    const succeeded = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
    const failed = results.filter(r => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value.success)).length;

    // Show summary toast
    if (failed === 0) {
        toastStore.success(`All ${vms.length} VMs ${verb.past.toLowerCase()} successfully`, {
            title: 'Bulk Action Complete',
            icon: 'check_circle',
            duration: 4000
        });
    } else if (succeeded === 0) {
        toastStore.error(`Failed to ${action} all VMs`, {
            title: 'Bulk Action Failed',
            icon: 'error',
            duration: 5000
        });
    } else {
        toastStore.warning(`${succeeded} succeeded, ${failed} failed`, {
            title: 'Bulk Action Partial Success',
            icon: 'warning',
            duration: 5000
        });
    }

    return { succeeded, failed };
}

/**
 * Example: Delete VM with confirmation toast pattern.
 * This demonstrates how to use toasts for user confirmation flows.
 */
export async function deleteVMWithConfirmation(
    vmId: string,
    vmName?: string,
    onConfirm?: () => void
): Promise<void> {
    // You would typically use a modal for confirmation,
    // but this shows how toasts can be used for simple confirmations
    toastStore.warning('This action cannot be undone', {
        title: `Delete VM "${vmName}"?`,
        icon: 'delete',
        persistent: true,
        action: {
            label: 'Confirm Delete',
            callback: async () => {
                toastStore.clear(); // Clear the confirmation toast
                await executeVMAction('delete', vmId, vmName);
                if (onConfirm) onConfirm();
            }
        }
    });
}
