import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
	plugins: [
		sveltekit(),
		VitePWA({
			registerType: 'autoUpdate',
			strategies: 'injectManifest',
			srcDir: 'src',
			filename: 'service-worker.ts',
			manifest: {
				name: 'Aether-V Management Console',
				short_name: 'Aether-V',
				description: 'Enterprise Hyper-V infrastructure management',
				theme_color: '#1976d2',
				background_color: '#ffffff',
				display: 'standalone',
				icons: [
					{
						src: '/assets/Logo.png',
						sizes: '512x512',
						type: 'image/png',
						purpose: 'any maskable'
					}
				]
			},
			injectManifest: {
				globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
				// Increase file size limit to 10MB to allow larger chunks
				maximumFileSizeToCacheInBytes: 10 * 1024 * 1024,
				// Exclude specific large files from precaching
				globIgnores: [
					'**/swagger-ui-dist/**',
					'**/*.map'
				]
			},
			devOptions: {
				enabled: false, // Disable in dev for faster iteration
				type: 'module'
			},
			workbox: {
				// These options only apply when using generateSW strategy
				// We're using injectManifest for full control
			}
		})
	],
	build: {
		// Asset inline threshold - inline small assets as base64
		assetsInlineLimit: 4096, // 4kb - icons and small images
		// Chunk size warning limit
		chunkSizeWarningLimit: 1000,
		rollupOptions: {
			output: {
				// Manual chunks for better caching
				manualChunks: (id) => {
					// Separate vendor chunks
					if (id.includes('node_modules')) {
						// Swagger UI is huge - separate it
						if (id.includes('swagger-ui-dist')) {
							return 'vendor-swagger';
						}
						// Svelte framework
						if (id.includes('svelte')) {
							return 'vendor-svelte';
						}
						// Everything else
						return 'vendor';
					}
				}
			}
		}
	}
});
