import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://svelte.dev/docs/kit/integrations
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	compilerOptions: {
		runes: true  // Enable Svelte 5 runes mode
	},
	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',  // SPA mode - all routes handled by client-side router
			precompress: false,
			strict: true
		}),
		paths: {
			// Migration Path Configuration
			// 
			// DEVELOPMENT/PREVIEW (Current): base: '/next-ui'
			// - Next-UI runs alongside old UI at /next-ui path
			// - Old UI continues at root path
			// - Allows gradual migration and testing
			//
			// PRODUCTION (When ready to migrate):
			// 1. Change base to empty string: base: ''
			// 2. Rebuild next-ui: npm run build
			// 3. Update server/app/main.py to mount next-ui at root instead of /next-ui
			// 4. Remove or relocate old UI static files
			//
			// This simple configuration change makes migration a one-line edit
			base: '/next-ui'
		}
	}
};

export default config;
