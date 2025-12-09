import { writable } from 'svelte/store';

interface Toast {
	id: number;
	type: 'success' | 'error' | 'warning' | 'info';
	message: string;
	duration?: number;
}

function createToastStore() {
	const { subscribe, update } = writable<Toast[]>([]);
	let nextId = 0;

	function addToast(type: Toast['type'], message: string, duration = 3000): number {
		const id = nextId++;
		update(toasts => [...toasts, { id, type, message, duration }]);
		
		if (duration > 0) {
			setTimeout(() => {
				removeToast(id);
			}, duration);
		}
		
		return id;
	}

	function removeToast(id: number) {
		update(toasts => toasts.filter(toast => toast.id !== id));
	}

	return {
		subscribe,
		addToast,
		removeToast
	};
}

export const toastStore = createToastStore();
