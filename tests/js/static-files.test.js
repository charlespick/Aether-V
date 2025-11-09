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
