<script lang="ts">
	/**
	 * Icon component using Material Symbols (rounded variant)
	 * 
	 * Usage:
	 *   <Icon name="cloud" />
	 *   <Icon name="settings" size={24} class="custom-class" />
	 * 
	 * Icons are imported from @material-symbols/svg-400 at build time via Vite.
	 * This provides optimal tree-shaking and no runtime overhead.
	 */
	
	interface Props {
		name: string;
		size?: number;
		class?: string;
	}
	
	let { name, size = 20, class: className = '' }: Props = $props();
	
	// Dynamic import of SVG at build time
	// Vite will resolve this and inline the SVG content
	const iconPath = `/node_modules/@material-symbols/svg-400/rounded/${name}.svg`;
	
	// Import the raw SVG content
	const modules = import.meta.glob('/node_modules/@material-symbols/svg-400/rounded/*.svg', {
		query: '?raw',
		eager: true
	});
	
	const svgContent = $derived(
		(modules[iconPath] as { default: string })?.default || ''
	);
</script>

<!-- Render the SVG with custom sizing and class -->
<span 
	class={`icon ${className}`} 
	style={`width: ${size}px; height: ${size}px;`}
	role="img"
	aria-hidden="true"
>
	{@html svgContent}
</span>

<style>
	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
	}
	
	.icon :global(svg) {
		width: 100%;
		height: 100%;
		fill: currentColor;
		stroke: currentColor;
	}
</style>
