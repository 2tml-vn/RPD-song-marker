# Track Specification - Master Visibility Toggle (YouTube Integration)

## Overview
Implement a "Master Toggle" for the JRPD Marker Pro UI. This feature allows the user to completely hide or show the marking panel using a dedicated button integrated directly into the YouTube player's control bar.

## Objectives
- **Zero Obstruction:** Provide a way to completely remove the UI from the screen when not actively marking.
- **Native Feel:** Integrate the toggle button seamlessly into the existing YouTube UI for a clean, professional look.
- **Background Functionality:** Ensure keyboard shortcuts (like 'A') and toast notifications continue to function even when the control panel is hidden.

## Functional Requirements
- **Integration:**
    - Detect the YouTube player control bar (`.ytp-right-controls`).
    - Inject a new button element that matches the style of native YouTube icons.
- **Master Toggle Logic:**
    - Clicking the injected button will toggle the `display` state of `#jrpd-marker-container` between `none` and `block`.
    - The state must be saved in `localStorage` (`jrpd-panel-hidden`).
- **Decoupled Feedback:**
    - The `showToast()` function must remain operational regardless of the panel's visibility.
    - Keyboard shortcuts must still trigger `doMark()` and show the toast even if the panel is `display: none`.

## Acceptance Criteria
- [ ] A new button appears in the YouTube control bar.
- [ ] Clicking the button hides/shows the JRPD panel.
- [ ] Pressing 'A' while the panel is hidden still creates a mark and shows the "Marked" toast notification.
- [ ] Panel visibility state is persistent across page reloads.
