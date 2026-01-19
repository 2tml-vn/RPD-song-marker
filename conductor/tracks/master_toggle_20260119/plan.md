# Implementation Plan - Master Visibility Toggle

## Phase 1: Core Integration
- [x] Task: Write tests to verify `showToast` is independent of the panel container.
- [x] Task: Implement `injectToggleBtn()` logic to find the YouTube control bar and insert the button.
- [x] Task: Create the `togglePanel()` function that manages `display: none` and `localStorage`.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Core Integration' (Protocol in workflow.md)

## Phase 2: Refactoring & Polish
- [x] Task: Update `initUI` to check the saved visibility state on startup.
- [x] Task: Ensure keyboard listeners remain globally active (not children of the container).
- [x] Task: Style the toggle button to match native YouTube SVG icons.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Refactoring & Polish' (Protocol in workflow.md) [checkpoint: 933f804]
