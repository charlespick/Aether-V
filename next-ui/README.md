# Next UI - Svelte-based UI for Aether-V

This directory contains the next-generation UI for Aether-V, built with SvelteKit and designed to replace the current vanilla JavaScript UI.

## Goals

- **UI Consistency**: Achieve consistent UI with less code by reusing view elements
- **Code Organization**: Break down large files (like main.js) into smaller, more manageable modules
- **Maintainability**: Create a more navigable codebase with smaller files and organized folders
- **Modern Stack**: Use SvelteKit with static build output, served by FastAPI

## Directory Structure

```
next-ui/
├── src/
│   ├── lib/
│   │   ├── components/
│   │   │   ├── common/        # Reusable UI components (Button, Input, Header, Sidebar)
│   │   │   ├── overlays/      # SlideOver and modal components
│   │   │   └── toast/         # Toast notification system
│   │   ├── views/
│   │   │   ├── overview/      # Overview/dashboard view
│   │   │   ├── vm/            # VM management view
│   │   │   ├── cluster/       # Cluster view
│   │   │   └── host/          # Host view
│   │   └── stores/            # Svelte stores for state management
│   ├── routes/                # SvelteKit routes
│   │   ├── +layout.svelte     # Main app layout
│   │   └── +page.svelte       # Home page
│   └── app.css                # Global styles and design tokens
├── static/                    # Static assets
├── build/                     # Build output (gitignored)
└── package.json
```

## Development

### Prerequisites

- Node.js 20+
- npm

### Setup

```bash
cd next-ui
npm install
```

### Development Server

```bash
npm run dev

# or start the server and open the app in a new browser tab
npm run dev -- --open
```

The dev server will start at `http://localhost:5173`

### Build

```bash
npm run build
```

This creates a static build in the `build/` directory that can be served by FastAPI.

You can preview the production build with `npm run preview`.

## Integration with FastAPI

The built static files are mounted at `/next-ui/` in the FastAPI application. The old UI includes a "Next UI (Preview)" button in the sidebar that links to the new UI.

## Component Library

### Common Components
- **Button**: Reusable button with variants (primary, secondary, danger, ghost)
- **Input**: Text input with label and error state
- **Header**: Top navigation bar with search and profile
- **Sidebar**: Left navigation sidebar

### Overlays
- **SlideOver**: Slide-in panel for detail views

### Toast
- **ToastContainer**: Toast notification system for user feedback

## Views

Each view is a self-contained Svelte component that can be routed to:

- **Overview**: Dashboard with stats and quick actions
- **VM**: Virtual machine management (placeholder)
- **Cluster**: Cluster management (placeholder)
- **Host**: Host details (placeholder)

## Design Tokens

CSS custom properties are defined in `src/app.css` for consistent theming:

- Colors (background, text, accent, status)
- Spacing
- Border radius
- Shadows
- Transitions

## Future Enhancements

- Connect to FastAPI backend via WebSocket and REST APIs
- Implement full VM management
- Add cluster and host management
- Implement authentication integration
- Add more reusable components as needed
