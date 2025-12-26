/**
 * Toast System Demo
 * 
 * This file demonstrates all the capabilities of the enhanced toast notification system.
 * Import this in a component to test the various toast types and behaviors.
 */

import { toastStore } from '$lib/stores/toastStore';

/**
 * Demo: Basic toast types
 */
export function demoBasicToasts() {
    toastStore.success('Operation completed successfully');

    setTimeout(() => {
        toastStore.error('Something went wrong');
    }, 500);

    setTimeout(() => {
        toastStore.warning('Please review your settings');
    }, 1000);

    setTimeout(() => {
        toastStore.info('New feature available');
    }, 1500);
}

/**
 * Demo: Toasts with titles
 */
export function demoTitledToasts() {
    toastStore.success('Your changes have been saved', {
        title: 'Settings Updated',
        icon: 'save'
    });

    setTimeout(() => {
        toastStore.error('The server is unreachable', {
            title: 'Connection Failed',
            icon: 'cloud_off'
        });
    }, 500);
}

/**
 * Demo: Connection status toasts with countdown
 */
export function demoConnectionToasts() {
    // Simulate disconnection with 5 second countdown
    const toastId = toastStore.connectionStatus('disconnected', 5, () => {
        console.log('User clicked retry');
        toastStore.remove(toastId);
        demoReconnecting();
    });
}

export function demoReconnecting() {
    // Show reconnecting with 3 second countdown
    const toastId = toastStore.connectionStatus('reconnecting', 3);

    // Simulate successful reconnection after 3 seconds
    setTimeout(() => {
        toastStore.remove(toastId);
        toastStore.connectionStatus('connected');
    }, 3000);
}

/**
 * Demo: Action toasts (VM operations)
 */
export function demoActionToasts() {
    // Action submitted
    toastStore.actionSubmitted('Starting', 'VM', 'WebServer-01');

    // Simulate action completion after 2 seconds
    setTimeout(() => {
        toastStore.actionSuccess('Started', 'VM', 'WebServer-01');
    }, 2000);
}

/**
 * Demo: Action failure
 */
export function demoActionFailure() {
    toastStore.actionSubmitted('Stopping', 'VM', 'Database-01');

    setTimeout(() => {
        toastStore.actionFailed('stop', 'VM', 'Database-01', 'VM is already stopped');
    }, 2000);
}

/**
 * Demo: Persistent toast (won't auto-dismiss)
 */
export function demoPersistentToast() {
    toastStore.warning('Manual intervention required', {
        title: 'Action Required',
        icon: 'priority_high',
        persistent: true
    });
}

/**
 * Demo: Toast with action button
 */
export function demoActionButton() {
    toastStore.info('A new version is available', {
        title: 'Update Available',
        icon: 'system_update',
        persistent: true,
        action: {
            label: 'Update Now',
            callback: () => {
                console.log('Updating...');
                toastStore.success('Update started', {
                    title: 'Updating',
                    icon: 'downloading'
                });
            }
        }
    });
}

/**
 * Demo: Non-dismissible toast
 */
export function demoNonDismissible() {
    toastStore.warning('System maintenance in progress', {
        title: 'Maintenance Mode',
        icon: 'build',
        persistent: true,
        dismissible: false
    });
}

/**
 * Demo: Overflow behavior (show more than 3 toasts)
 */
export function demoOverflow() {
    // Create 7 toasts to demonstrate overflow (max 3 visible)
    for (let i = 1; i <= 7; i++) {
        setTimeout(() => {
            toastStore.info(`This is notification #${i}`, {
                title: `Notification ${i}`,
                icon: 'notifications'
            });
        }, i * 200);
    }
}

/**
 * Demo: Countdown update pattern
 */
export function demoCountdownUpdates() {
    let countdown = 10;
    const toastId = toastStore.info(`Task will start in ${countdown} seconds`, {
        title: 'Scheduled Task',
        icon: 'schedule',
        persistent: true,
        countdown,
        updatable: true
    });

    const interval = setInterval(() => {
        countdown--;
        if (countdown <= 0) {
            clearInterval(interval);
            toastStore.remove(toastId);
            toastStore.success('Task started', {
                title: 'Scheduled Task',
                icon: 'play_arrow'
            });
        } else {
            toastStore.updateToast(toastId, {
                message: `Task will start in ${countdown} seconds`,
                countdown
            });
        }
    }, 1000);
}

/**
 * Demo: Complex workflow (simulates a deployment process)
 */
export function demoComplexWorkflow() {
    // Step 1: Validation
    const validateId = toastStore.info('Checking prerequisites...', {
        title: 'Deploying Application',
        icon: 'fact_check',
        persistent: true,
        dismissible: false
    });

    setTimeout(() => {
        toastStore.remove(validateId);

        // Step 2: Building
        const buildId = toastStore.info('Compiling and packaging...', {
            title: 'Building',
            icon: 'construction',
            persistent: true,
            dismissible: false
        });

        setTimeout(() => {
            toastStore.remove(buildId);

            // Step 3: Deploying
            const deployId = toastStore.info('Uploading to servers...', {
                title: 'Deploying',
                icon: 'upload',
                persistent: true,
                dismissible: false
            });

            setTimeout(() => {
                toastStore.remove(deployId);

                // Step 4: Success
                toastStore.success('Application is now live', {
                    title: 'Deployment Complete',
                    icon: 'check_circle',
                    duration: 5000
                });
            }, 3000);
        }, 3000);
    }, 2000);
}

/**
 * Clear all toasts
 */
export function clearAllToasts() {
    toastStore.clear();
}
