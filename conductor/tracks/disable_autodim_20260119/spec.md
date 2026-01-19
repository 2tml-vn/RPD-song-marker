# Track Specification - Disable Auto-Dimming Logic

## Overview
The user wants to remove the "Adaptive Dimming" feature where the panel automatically reduces its opacity to 20% without user intervention. Instead, the panel should remain at 100% opacity unless explicitly toggled by the user via the "Eye" icon.

## Objectives
- **Remove Auto-Dimming:** Strip the logic that automatically triggers the dimmed state based on timers or page state.
- **Maintain Manual Toggle:** Keep the "Eye" icon functionality, allowing the user to manually switch between fully visible (100% opacity) and dimmed states.
- **Persistent Visibility:** Ensure the panel starts at 100% opacity by default upon page load or video switch.
- **Unobtrusive Dimming:** When in the dimmed state, ensure the UI remains helpful but non-distracting.

## Functional Requirements
- **Logic Cleanup:**
    - Identify and remove any `setTimeout` or `setInterval` calls that modify `container.style.opacity` or the `isLocked` state automatically.
    - Remove the initial `container.style.opacity = "0.2"` assignment in `initUI`.
- **Manual Toggle Behavior:**
    - The "Eye" icon click handler will remain the sole controller of the `isLocked` state.
    - When `isLocked` is `true`, the container opacity should be `1`.
    - When `isLocked` is `false`, the container opacity should be `0.2` (or a similar non-distracting value).
- **UI Enhancement:**
    - Ensure the "Eye" icon itself remains visible enough to be clicked when the panel is dimmed, but ensure it doesn't distract from the video content.

## Acceptance Criteria
- [ ] On page load, the JRPD panel appears at 100% opacity.
- [ ] The panel does NOT automatically fade or dim after any amount of time.
- [ ] Clicking the "Eye" icon correctly toggles the panel between fully visible and dimmed.
- [ ] The panel remains at 100% opacity even during video playback unless the user manually dims it.
