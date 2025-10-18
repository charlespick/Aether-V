# Dynamic View & Overlay System Documentation

## Overview

The Aether-V application uses a modular, maintainable architecture for dynamic content views and overlay panels. This system allows for easy composition and separation of concerns.

## Architecture Components

### 1. View System (`views.js`)

The view system manages dynamic content in the main panel. Each view is a self-contained class that can render and manage its own state.

#### ViewManager Class

**Purpose**: Manages view registration, switching, and lifecycle

**Key Methods**:

- `init(containerId)` - Initialize the view manager with a container element
- `registerView(name, viewClass)` - Register a new view type
- `switchView(viewName, data)` - Switch to a different view with optional data
- `updateNavigation(viewName)` - Update sidebar navigation active state

**Usage**:

```javascript
viewManager.init("view-container");
await viewManager.switchView("overview");
await viewManager.switchView("host", { hostname: "hyperv01.example.com" });
```

#### BaseView Class

All views extend `BaseView` and implement these methods:

- `constructor(data)` - Initialize with data
- `async render()` - Return HTML string for the view
- `init()` - Setup event listeners and interactive elements
- `cleanup()` - Clean up before view is destroyed

#### Built-in Views

1. **OverviewView** - Aether root view showing cluster overview
2. **ClusterView** - Cluster details and host grid
3. **HostView** - Individual host details and VMs
4. **VMView** - Virtual machine details and actions

#### Creating a Custom View

```javascript
class CustomView extends BaseView {
  async render() {
    const data = await this.fetchData();
    return `
            <h1 class="page-title">${this.data.title}</h1>
            <div class="view-section">
                <!-- Your content here -->
            </div>
        `;
  }

  init() {
    // Setup event listeners
    document.querySelector(".my-button")?.addEventListener("click", () => {
      console.log("Button clicked");
    });
  }

  cleanup() {
    // Remove event listeners, clear timers, etc.
  }

  async fetchData() {
    const response = await fetch("/api/v1/my-endpoint");
    return response.json();
  }
}

// Register the view
viewManager.registerView("custom", CustomView);

// Use the view
await viewManager.switchView("custom", { title: "My Custom View" });
```

### 2. Overlay System (`overlay.js`)

The overlay system provides a reusable slide-out panel for settings, notifications, and detail views.

#### OverlayManager Class

**Purpose**: Manages overlay panels with dimmed backdrop

**Key Methods**:

- `init()` - Initialize overlay DOM and event listeners
- `registerOverlay(name, overlayClass)` - Register overlay type
- `open(overlayName, data)` - Open an overlay with data
- `close()` - Close the current overlay

**Usage**:

```javascript
overlayManager.init();
overlayManager.open("settings");
overlayManager.open("job-details", { job: jobData });
```

#### Features

- **Dimmed backdrop** - Covers entire screen with semi-transparent black
- **Right-side panel** - 60% width white panel sliding in from right
- **Close button** - Subtle arrow button to dismiss
- **ESC key support** - Close overlay with Escape key
- **Click outside** - Click backdrop to close
- **Smooth animations** - CSS transitions for open/close

#### BaseOverlay Class

All overlays extend `BaseOverlay` and implement:

- `getTitle()` - Return overlay title string
- `async render()` - Return HTML content
- `init()` - Setup interactive elements
- `cleanup()` - Clean up before close

#### Built-in Overlays

1. **SettingsOverlay** - Application settings
2. **JobDetailsOverlay** - Job execution details and logs
3. **NotificationsOverlay** - System notifications list

#### Creating a Custom Overlay

```javascript
class MyCustomOverlay extends BaseOverlay {
  getTitle() {
    return "Custom Overlay";
  }

  async render() {
    return `
            <div class="settings-section">
                <h3>Section Title</h3>
                <p>Content here</p>
            </div>
            <div class="settings-actions">
                <button class="btn btn-secondary" onclick="overlayManager.close()">
                    Cancel
                </button>
                <button class="btn" onclick="myCustomOverlay.save()">
                    Save
                </button>
            </div>
        `;
  }

  init() {
    // Load data, setup listeners
  }

  save() {
    // Handle save action
    overlayManager.close();
  }
}

// Register the overlay
overlayManager.registerOverlay("my-custom", MyCustomOverlay);

// Use the overlay
overlayManager.open("my-custom", { someData: "value" });
```

## Integration Patterns

### Navigation Integration

Views are triggered from sidebar navigation:

```javascript
// In setupNavigation()
document
  .querySelector('[data-view="overview"]')
  ?.addEventListener("click", () => {
    viewManager.switchView("overview");
  });

// Dynamic host navigation
onclick = "viewManager.switchView('host', { hostname: '${hostname}' })";

// Dynamic VM navigation
onclick =
  "viewManager.switchView('vm', { name: '${vm.name}', host: '${vm.host}' })";
```

### Overlay Integration

Overlays are opened from buttons and notifications:

```javascript
// Settings button
document.getElementById("sidebar-settings")?.addEventListener("click", () => {
  overlayManager.open("settings");
});

// Notification bell
document
  .querySelector('[title="Notifications"]')
  ?.addEventListener("click", () => {
    overlayManager.open("notifications");
  });

// From view content
<button onclick="overlayManager.open('job-details', { job: {...} })">
  View Details
</button>;
```

### Data Flow

1. **Initial Load**:

   ```javascript
   await loadInventory(); // Fetch from API
   updateSidebarNavigation(data); // Update nav tree
   await viewManager.switchView("overview"); // Show default view
   ```

2. **View Switching**:

   ```javascript
   await viewManager.switchView("host", { hostname: "host.example.com" });
   // → HostView.render() fetches fresh data
   // → Updates main content
   // → Updates navigation active state
   ```

3. **Overlay Opening**:
   ```javascript
   overlayManager.open("job-details", { job: jobData });
   // → JobDetailsOverlay.render() with data
   // → Slides in from right
   // → Dims background
   ```

## CSS Classes Reference

### View Styles

- `.view-section` - Standard section container
- `.section-header` - Section header with title
- `.info-grid` - Grid for info items
- `.info-item` - Single info row
- `.info-label` - Info label text
- `.host-card` - Clickable host card
- `.vm-card` - Clickable VM card
- `.quick-actions` - Action button row
- `.action-btn` - Action button style

### Overlay Styles

- `.overlay-container` - Main overlay wrapper
- `.overlay-backdrop` - Dimmed background
- `.overlay-panel` - White slide-out panel
- `.overlay-header` - Fixed overlay header
- `.overlay-content` - Scrollable content area
- `.overlay-close` - Close button
- `.settings-section` - Settings section
- `.settings-actions` - Button row at bottom

## Server-Side Integration

### API Endpoints

Views fetch data from these endpoints:

```python
@app.get("/api/v1/inventory")
async def get_inventory():
    return {
        "hosts": [...],
        "vms": [...],
        "total_hosts": 2,
        "total_vms": 5
    }

@app.get("/api/v1/hosts/{hostname}")
async def get_host_details(hostname: str):
    return {
        "hostname": "...",
        "connected": true,
        "last_seen": "...",
        "vms": [...]
    }

@app.get("/api/v1/vms/{vm_name}")
async def get_vm_details(vm_name: str):
    return {
        "name": "...",
        "state": "Running",
        "host": "...",
        "cpu_cores": 4,
        "memory_gb": 8.0
    }
```

### Server-Rendered Views (Optional)

You can pre-render views on the server:

```python
@app.get("/views/host/{hostname}")
async def render_host_view(hostname: str):
    host = get_host(hostname)
    return templates.TemplateResponse("views/host.html", {
        "host": host,
        "vms": get_vms_for_host(hostname)
    })
```

Then load in JavaScript:

```javascript
class HostView extends BaseView {
  async render() {
    const response = await fetch(`/views/host/${this.data.hostname}`);
    return await response.text();
  }
}
```

## Best Practices

1. **Keep views focused** - One view = one purpose
2. **Fetch fresh data** - Each view fetches its own data
3. **Clean up properly** - Remove listeners in cleanup()
4. **Handle errors** - Graceful fallbacks for failed fetches
5. **Use semantic HTML** - Proper heading hierarchy
6. **Accessibility** - ARIA labels, keyboard navigation
7. **Mobile-first** - Responsive design in all views
8. **Consistent styling** - Use existing CSS classes

## File Structure

```
/server/app/static/
├── main.js          # Main app logic, auth, navigation
├── views.js         # View system and view classes
├── overlay.js       # Overlay system and overlay classes
└── main.css         # All styles including views and overlays

/server/app/templates/
└── index.html       # Main template with view-container
```

## Example: Adding a New Feature

Let's add a "Network Details" overlay:

```javascript
// 1. Create the overlay class in overlay.js
class NetworkDetailsOverlay extends BaseOverlay {
  getTitle() {
    return "Network Configuration";
  }

  async render() {
    const network = await fetch(`/api/v1/networks/${this.data.networkId}`).then(
      (r) => r.json()
    );

    return `
            <div class="settings-section">
                <h3>Network Information</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">Name:</span>
                        <span>${network.name}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Type:</span>
                        <span>${network.type}</span>
                    </div>
                </div>
            </div>
        `;
  }
}

// 2. Register it
overlayManager.registerOverlay("network-details", NetworkDetailsOverlay);

// 3. Use it anywhere
<button onclick="overlayManager.open('network-details', { networkId: 'net-1' })">
  View Network
</button>;
```

## Troubleshooting

**View not updating?**

- Check browser console for errors
- Ensure data is being fetched
- Verify view is registered

**Overlay not closing?**

- Check if cleanup() is called
- Verify ESC key handler is attached
- Check for JavaScript errors

**Navigation not working?**

- Ensure viewManager.init() is called
- Check if navigation handlers are attached
- Verify data attributes are correct

**Styling issues?**

- Check if CSS classes are correct
- Verify responsive breakpoints
- Inspect element structure
