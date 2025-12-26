/**
 * Modal state management store
 * Centralized store for managing modal open/close state and data
 */

import { writable } from 'svelte/store';

export interface ModalState {
	type: 'disk-create' | 'disk-edit' | 'nic-create' | 'nic-edit' | 'vm-provision' | 'settings' | null;
	data?: any;
	onSuccess?: (...args: any[]) => void;
}

function createModalStore() {
	const { subscribe, set, update } = writable<ModalState>({
		type: null,
		data: undefined,
		onSuccess: undefined
	});

	return {
		subscribe,

		/**
		 * Open a modal with optional data and success callback
		 */
		open(type: NonNullable<ModalState['type']>, data?: any, onSuccess?: (...args: any[]) => void) {
			set({ type, data, onSuccess });
		},

		/**
		 * Close the currently open modal
		 */
		close() {
			set({ type: null, data: undefined, onSuccess: undefined });
		},

		/**
		 * Replace the current modal with a new one
		 * Useful for navigation between related modals
		 */
		replace(type: NonNullable<ModalState['type']>, data?: any, onSuccess?: (...args: any[]) => void) {
			set({ type, data, onSuccess });
		},

		/**
		 * Check if a specific modal is currently open
		 */
		isOpen(type: NonNullable<ModalState['type']>): boolean {
			let currentState: ModalState;
			subscribe((state) => (currentState = state))();
			return currentState!.type === type;
		}
	};
}

export const modalStore = createModalStore();
