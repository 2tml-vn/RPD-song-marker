# Implementation Plan - Disable Auto-Dimming Logic

## Phase 1: Logic Removal & Initialization Fix
- [x] Task: Write verification tests ensuring `isLocked` state doesn't change automatically.
- [x] Task: Locate and remove the initial `container.style.opacity = "0.2"` assignment in `jrpd_marker.user.js`.
- [x] Task: Scan `jrpd_marker.user.js` for any `setTimeout`/`setInterval` or event listeners (like video play/pause) that auto-trigger dimming and remove them.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Logic Removal & Initialization Fix' (Protocol in workflow.md) [checkpoint: c6efef0]

## Phase 2: Manual Toggle Reinforcement
- [ ] Task: Write tests for the "Eye" icon click handler to ensure correct opacity toggling.
- [ ] Task: Verify the `lockBtn.onclick` logic ensures `isLocked` and `opacity` are updated correctly and consistently.
- [ ] Task: Ensure the `isLocked` state is initialized to `true` (Visible) by default.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Manual Toggle Reinforcement' (Protocol in workflow.md)
