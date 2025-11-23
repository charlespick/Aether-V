const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const staticDir = path.join(__dirname, '..', '..', 'server', 'app', 'static');

function readFile(relativePath) {
  const fullPath = path.join(staticDir, relativePath);
  return fs.readFileSync(fullPath, 'utf8');
}

test('main.js should define provisioning availability helper', () => {
  const content = readFile('main.js');
  assert.match(
    content,
    /function applyProvisioningAvailability/, 
    'expected applyProvisioningAvailability helper to be present'
  );
});

test('websocket.js should reset reconnect delay after a successful connection', () => {
  const content = readFile('websocket.js');
  assert.match(
    content,
    /this\.reconnectDelay = 1000;\s*\/\/ Start with 1 second/,
    'expected reconnectDelay reset to be documented in websocket.js'
  );
});

test('overlay.js should define an overlay manager class', () => {
  const content = readFile('overlay.js');
  assert.match(content, /class OverlayManager/);
});

test('views.js should include overview view markup', () => {
  const content = readFile('views.js');
  assert.match(
    content,
    /<h1 class=\"page-title\">Aether Overview<\/h1>/,
    'expected overview page title markup in views.js'
  );
});

test('overlay.js disk and NIC overlays should not reference schema API', () => {
  const content = readFile('overlay.js');
  
  // Extract class definitions more reliably
  const extractClass = (className) => {
    const pattern = new RegExp(`class ${className} extends BaseOverlay \\{[\\s\\S]*?(?=\\nclass [A-Z]|\\n\\/\\/ [A-Z]|$)`);
    const match = content.match(pattern);
    return match ? match[0] : '';
  };
  
  const diskCreateClass = extractClass('DiskCreateOverlay');
  const nicCreateClass = extractClass('NicCreateOverlay');
  
  // Ensure schema API endpoints are not referenced
  assert.doesNotMatch(
    diskCreateClass,
    /\/api\/v1\/schema\/disk-create/,
    'DiskCreateOverlay should not reference /api/v1/schema/disk-create'
  );
  
  assert.doesNotMatch(
    nicCreateClass,
    /\/api\/v1\/schema\/nic-create/,
    'NicCreateOverlay should not reference /api/v1/schema/nic-create'
  );
  
  assert.doesNotMatch(
    diskCreateClass,
    /fetchSchema/,
    'DiskCreateOverlay should not have fetchSchema method'
  );
  
  assert.doesNotMatch(
    nicCreateClass,
    /fetchSchema/,
    'NicCreateOverlay should not have fetchSchema method'
  );
});

test('overlay.js disk and NIC overlays should use Pydantic-based forms', () => {
  const content = readFile('overlay.js');
  
  // Extract class definitions using helper function
  const extractClass = (className) => {
    const pattern = new RegExp(`class ${className} extends BaseOverlay \\{[\\s\\S]*?(?=\\nclass [A-Z]|\\n\\/\\/ [A-Z]|$)`);
    const match = content.match(pattern);
    return match ? match[0] : '';
  };
  
  const diskCreateClass = extractClass('DiskCreateOverlay');
  const nicCreateClass = extractClass('NicCreateOverlay');
  
  // Verify DiskCreateOverlay renders hardcoded form
  assert.match(
    diskCreateClass,
    /disk-size-gb/,
    'DiskCreateOverlay should render hardcoded disk-size-gb field'
  );
  
  // Verify NicCreateOverlay renders hardcoded form
  assert.match(
    nicCreateClass,
    /name="network"/,
    'NicCreateOverlay should render hardcoded network field'
  );
  
  // Verify forms don't send schema_version
  assert.doesNotMatch(
    diskCreateClass,
    /schema_version/,
    'DiskCreateOverlay should not send schema_version in API request'
  );
  
  assert.doesNotMatch(
    nicCreateClass,
    /schema_version/,
    'NicCreateOverlay should not send schema_version in API request'
  );
});
