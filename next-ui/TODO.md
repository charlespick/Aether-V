# Next-UI Future Improvements

## Code Quality

### Type Safety
- [ ] Update component `children` props from `any` to `Snippet` type in Svelte 5
  - Affects: Button, SlideOver, and other components with children
  - Reference: [Svelte 5 Snippet type](https://svelte.dev/docs/svelte/snippet)

### Accessibility
- [ ] Add proper ARIA attributes to Header profile dropdown
  - `role="menu"` for dropdown
  - `aria-expanded` state
  - Keyboard navigation support (Arrow keys, Enter, Escape)
  - Focus management

### Component Patterns
- [ ] Consider event handler pattern for toast close instead of direct store access
  - Makes components more decoupled and testable

## Features

### High Priority
- [ ] Connect to FastAPI WebSocket for real-time updates
- [ ] Implement authentication flow
- [ ] Add VM management functionality
- [ ] Add cluster and host detail views

### Medium Priority
- [ ] Implement global loading states
- [ ] Add error boundaries
- [ ] Create more reusable components:
  - Table/DataGrid
  - Form components (Select, Checkbox, Radio)
  - Modal
  - Dropdown menu
  - Tabs
  - Progress indicators

### Low Priority
- [ ] Dark/light theme toggle
- [ ] Keyboard shortcuts
- [ ] Advanced search/filtering
- [ ] Breadcrumb navigation
- [ ] User preferences persistence

## Testing

- [ ] Set up Vitest for unit testing
- [ ] Add component tests
- [ ] Add integration tests for views
- [ ] Set up Playwright for E2E tests

## Performance

- [ ] Add virtual scrolling for large lists
- [ ] Implement pagination
- [ ] Add caching strategy for API calls
- [ ] Optimize bundle size

## Documentation

- [ ] Add Storybook for component documentation
- [ ] Create component usage examples
- [ ] Document API integration patterns
- [ ] Add contribution guidelines
