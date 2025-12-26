/**
 * Toast Notification Store
 * 
 * Manages toast notifications with support for:
 * - Multiple notification types (success, error, warning, info)
 * - Auto-dismiss with configurable duration
 * - Persistent notifications (duration = 0)
 * - Icon support (cached for offline)
 * - Action buttons
 * - Connection status notifications
 */

import { writable, get } from 'svelte/store';

interface Toast {
	id: number;
	type: 'success' | 'error' | 'warning' | 'info';
	title?: string; // Optional headline for the toast
	message: string; // Subtext or main message
	duration?: number;
	icon?: string; // Icon name for cached icon display
	action?: {
		label: string;
		callback: () => void;
	};
	persistent?: boolean; // If true, won't auto-dismiss
	dismissible?: boolean; // If false, hide close button (defaults to true)
	countdown?: number; // Countdown value in seconds (for dynamic updates)
	updatable?: boolean; // If true, allows content updates via updateToast
}

const toasts = writable<Toast[]>([]);

class ToastStore {
	private nextId = 0;
	private countdownIntervals = new Map<number, number>(); // Track countdown timers

	// Store subscription
	subscribe = toasts.subscribe;

	/**
	 * Update an existing toast's properties.
	 * Useful for countdown updates or changing content dynamically.
	 */
	updateToast(id: number, updates: Partial<Omit<Toast, 'id'>>) {
		toasts.update(current =>
			current.map(toast => (toast.id === id ? { ...toast, ...updates } : toast))
		);
	}

	/**
	 * Start a countdown timer for a toast.
	 * The countdown will decrement every second and update the toast.
	 */
	private startCountdown(id: number, initialCount: number, onComplete?: () => void) {
		// Clear any existing countdown for this toast
		this.stopCountdown(id);

		let count = initialCount;
		const intervalId = window.setInterval(() => {
			count--;
			if (count <= 0) {
				this.stopCountdown(id);
				if (onComplete) {
					onComplete();
				}
			} else {
				this.updateToast(id, { countdown: count });
			}
		}, 1000);

		this.countdownIntervals.set(id, intervalId);
	}

	/**
	 * Stop a countdown timer for a toast.
	 */
	private stopCountdown(id: number) {
		const intervalId = this.countdownIntervals.get(id);
		if (intervalId) {
			clearInterval(intervalId);
			this.countdownIntervals.delete(id);
		}
	}

	/**
	 * Add a toast notification.
	 * Returns the toast ID for manual removal.
	 */
	private addToast(type: Toast['type'], message: string, options: Partial<Toast> = {}): number {
		const id = this.nextId++;
		const duration = options.persistent ? 0 : (options.duration ?? 3000);

		const toast: Toast = {
			id,
			type,
			title: options.title,
			message,
			duration,
			icon: options.icon,
			action: options.action,
			persistent: options.persistent,
			dismissible: options.dismissible ?? true,
			countdown: options.countdown,
			updatable: options.updatable ?? false
		};

		toasts.update(current => [...current, toast]);

		// Start countdown if specified
		if (options.countdown && options.countdown > 0) {
			this.startCountdown(id, options.countdown, options.action?.callback);
		}

		// Auto-dismiss after duration (unless persistent or duration = 0)
		if (duration > 0 && !options.persistent) {
			setTimeout(() => {
				this.remove(id);
			}, duration);
		}

		return id;
	}

	/**
	 * Remove a toast by ID.
	 */
	remove(id: number) {
		this.stopCountdown(id);
		toasts.update(current => current.filter(toast => toast.id !== id));
	}

	/**
	 * Clear all toasts.
	 */
	clear() {
		toasts.set([]);
	}

	/**
	 * Show a success notification.
	 */
	success(message: string, options?: Partial<Toast>) {
		return this.addToast('success', message, { icon: 'check_circle', ...options });
	}

	/**
	 * Show an error notification.
	 */
	error(message: string, options?: Partial<Toast>) {
		return this.addToast('error', message, {
			icon: 'error',
			duration: 5000, // Errors stay longer
			...options
		});
	}

	/**
	 * Show a warning notification.
	 */
	warning(message: string, options?: Partial<Toast>) {
		return this.addToast('warning', message, {
			icon: 'warning',
			duration: 4000,
			...options
		});
	}

	/**
	 * Show an info notification.
	 */
	info(message: string, options?: Partial<Toast>) {
		return this.addToast('info', message, { icon: 'info', ...options });
	}

	/**
	 * Show a connection error notification (persistent with retry action).
	 */
	connectionError(onRetry?: () => void) {
		const current = get(toasts);
		const existingConnectionErrors = current.filter(
			t => t.type === 'error' && t.message.includes('connection')
		);

		// Don't duplicate connection error toasts
		if (existingConnectionErrors.length > 0) {
			return existingConnectionErrors[0].id;
		}

		return this.error('Lost connection to server', {
			icon: 'cloud_off',
			persistent: true,
			action: onRetry ? {
				label: 'Retry',
				callback: onRetry
			} : undefined
		});
	}

	/**
	 * Show a connection restored notification.
	 */
	connectionRestored() {
		// Remove any existing connection error toasts
		toasts.update(current =>
			current.filter(t => !(t.type === 'error' && t.message.includes('connection')))
		);

		return this.success('Connection restored', {
			icon: 'cloud_done',
			duration: 3000
		});
	}

	// ========================================
	// Specialized Toast Factory Methods
	// ========================================

	/**
	 * Show a connection status notification with countdown.
	 * @param status - Connection status
	 * @param countdown - Seconds until next retry attempt
	 * @param onRetry - Callback for manual retry button
	 */
	connectionStatus(
		status: 'disconnected' | 'reconnecting' | 'connected',
		countdown?: number,
		onRetry?: () => void
	): number {
		// Remove existing connection toasts
		const current = get(toasts);
		const existingConnectionToasts = current.filter(
			t => t.title === 'Connection Lost' || t.title === 'Reconnecting' || t.title === 'Connected'
		);
		existingConnectionToasts.forEach(t => this.remove(t.id));

		if (status === 'disconnected') {
			return this.addToast('error', countdown ? `Retrying in ${countdown} seconds` : 'Unable to reach server', {
				title: 'Connection Lost',
				icon: 'cloud_off',
				persistent: true,
				dismissible: false,
				countdown,
				updatable: true,
				action: onRetry ? {
					label: 'Retry Now',
					callback: onRetry
				} : undefined
			});
		} else if (status === 'reconnecting') {
			return this.addToast('warning', countdown ? `Attempting to reconnect (${countdown}s)` : 'Attempting to reconnect...', {
				title: 'Reconnecting',
				icon: 'sync',
				persistent: true,
				dismissible: false,
				countdown,
				updatable: true
			});
		} else {
			return this.addToast('success', 'Successfully reconnected to server', {
				title: 'Connected',
				icon: 'cloud_done',
				duration: 3000
			});
		}
	}

	/**
	 * Show an action submitted notification.
	 * @param action - The action being performed (e.g., "Start", "Stop", "Delete")
	 * @param entity - The entity being acted upon (e.g., "VM", "Host")
	 * @param entityName - Optional specific name of the entity
	 */
	actionSubmitted(action: string, entity: string, entityName?: string): number {
		const entityDesc = entityName ? `${entity} "${entityName}"` : entity;
		return this.addToast('info', `Command sent to server`, {
			title: `${action} ${entityDesc}`,
			icon: 'send',
			duration: 2000
		});
	}

	/**
	 * Show an action success notification.
	 * @param action - The action that was performed
	 * @param entity - The entity that was acted upon
	 * @param entityName - Optional specific name of the entity
	 */
	actionSuccess(action: string, entity: string, entityName?: string): number {
		const entityDesc = entityName ? `${entity} "${entityName}"` : entity;
		return this.addToast('success', `Operation completed successfully`, {
			title: `${action} ${entityDesc}`,
			icon: 'check_circle',
			duration: 4000
		});
	}

	/**
	 * Show an action failed notification.
	 * @param action - The action that failed
	 * @param entity - The entity involved
	 * @param entityName - Optional specific name of the entity
	 * @param reason - Optional failure reason
	 */
	actionFailed(action: string, entity: string, entityName?: string, reason?: string): number {
		const entityDesc = entityName ? `${entity} "${entityName}"` : entity;
		const message = reason || 'Operation failed';
		return this.addToast('error', message, {
			title: `Failed to ${action} ${entityDesc}`,
			icon: 'error',
			duration: 6000
		});
	}
}

// Export singleton instance
export const toastStore = new ToastStore();

// Export type for use in components
export type { Toast };
