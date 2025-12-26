#!/usr/bin/env node

/**
 * Icon Sprite Generator
 * 
 * Generates an optimized SVG sprite sheet from Material Symbols icons used in the application.
 * This provides faster loading and better caching for frequently used icons.
 * 
 * Usage:
 *   node scripts/generate-icon-sprite.js [output-dir]
 *   or import { generateIconSprite } from './scripts/generate-icon-sprite.js'
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Icons used in the application (from server/icons.json)
const ICONS = [
    'cloud',
    'grid_view',
    'computer',
    'memory',
    'dns',
    'settings',
    'notifications',
    'account_circle',
    'search',
    'add',
    'refresh',
    'more_vert',
    'play_arrow',
    'stop',
    'restart_alt',
    'delete',
    'edit',
    'visibility',
    'download',
    'upload',
    'check_circle',
    'error',
    'warning',
    'info',
    'close',
    'menu',
    'circles_ext',
    'host',
    'play_circle',
    'power_settings_new',
    'pause_circle',
    'arrow_drop_down',
    'circle'
];

const ICON_VARIANT = 'rounded';
const ICON_WEIGHT = '400';

export function generateIconSprite(outputDir) {
    const iconSourcePath = path.resolve(__dirname, '../node_modules/@material-symbols/svg-400', ICON_VARIANT);
    const outputPath = path.join(outputDir, 'icon-sprite.svg');

    console.log('🎨 Generating icon sprite...');
    console.log(`Source: ${iconSourcePath}`);
    console.log(`Output: ${outputPath}`);
    console.log(`Icons: ${ICONS.length}`);

    let spriteContent = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" style="display: none;">
  <defs>
`;

    let successCount = 0;
    let failCount = 0;

    ICONS.forEach(iconName => {
        const iconFilePath = path.join(iconSourcePath, `${iconName}.svg`);

        try {
            if (!fs.existsSync(iconFilePath)) {
                console.warn(`⚠️  Icon not found: ${iconName}`);
                failCount++;
                return;
            }

            const iconContent = fs.readFileSync(iconFilePath, 'utf-8');

            // Extract the SVG path/content (remove svg wrapper)
            const pathMatch = iconContent.match(/<path[^>]*d="([^"]+)"[^>]*\/>/);

            if (pathMatch) {
                const pathData = pathMatch[0];
                spriteContent += `    <symbol id="icon-${iconName}" viewBox="0 0 24 24">
      ${pathData}
    </symbol>
`;
                successCount++;
            } else {
                console.warn(`⚠️  Could not parse icon: ${iconName}`);
                failCount++;
            }

        } catch (error) {
            console.error(`❌ Error processing icon ${iconName}:`, error.message);
            failCount++;
        }
    });

    spriteContent += `  </defs>
</svg>`;

    // Ensure output directory exists
    if (!fs.existsSync(outputDir)) {
        fs.mkdirSync(outputDir, { recursive: true });
    }

    // Write sprite file
    fs.writeFileSync(outputPath, spriteContent, 'utf-8');

    console.log('');
    console.log('✅ Icon sprite generated successfully!');
    console.log(`   Success: ${successCount} icons`);
    console.log(`   Failed: ${failCount} icons`);
    console.log(`   Output: ${outputPath}`);
    console.log(`   Size: ${(Buffer.byteLength(spriteContent, 'utf8') / 1024).toFixed(2)} KB`);
}

// CLI usage
if (import.meta.url === `file://${process.argv[1]}`) {
    // Always output to static/ - it will be copied by SvelteKit during build
    // and ignored by git (added to .gitignore)
    const outputDir = path.resolve(__dirname, '../static');
    generateIconSprite(outputDir);
}
