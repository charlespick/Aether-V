import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'aether-v-theme';

interface ThemeState {
    mode: ThemeMode;
    resolved: ResolvedTheme;
}

function getSystemTheme(): ResolvedTheme {
    if (!browser) return 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function createThemeStore() {
    // Initialize from localStorage or default to system
    const getInitialMode = (): ThemeMode => {
        if (!browser) return 'dark';

        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'light' || stored === 'dark' || stored === 'system') {
            return stored;
        }

        return 'system';
    };

    const initialMode = getInitialMode();
    const initialResolved = initialMode === 'system' ? getSystemTheme() : initialMode;

    const { subscribe, set, update } = writable<ThemeState>({
        mode: initialMode,
        resolved: initialResolved
    });

    // Apply theme to DOM
    const applyTheme = (theme: ResolvedTheme) => {
        if (browser) {
            document.documentElement.setAttribute('data-theme', theme);
        }
    };

    // Listen for system theme changes
    if (browser) {
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', (e) => {
            update(state => {
                // Only update if we're in system mode
                if (state.mode === 'system') {
                    const newResolved = e.matches ? 'dark' : 'light';
                    applyTheme(newResolved);
                    return { ...state, resolved: newResolved };
                }
                return state;
            });
        });
    }

    // Apply initial theme
    applyTheme(initialResolved);

    return {
        subscribe,
        setMode: (mode: ThemeMode) => {
            const resolved = mode === 'system' ? getSystemTheme() : mode;

            if (browser) {
                localStorage.setItem(STORAGE_KEY, mode);
                applyTheme(resolved);
            }

            set({ mode, resolved });
        },
        toggle: () => {
            update(state => {
                // Cycle through: dark -> light -> system -> dark
                let newMode: ThemeMode;
                if (state.mode === 'dark') {
                    newMode = 'light';
                } else if (state.mode === 'light') {
                    newMode = 'system';
                } else {
                    newMode = 'dark';
                }

                const newResolved = newMode === 'system' ? getSystemTheme() : newMode;

                if (browser) {
                    localStorage.setItem(STORAGE_KEY, newMode);
                    applyTheme(newResolved);
                }

                return { mode: newMode, resolved: newResolved };
            });
        }
    };
}

export const themeStore = createThemeStore();
