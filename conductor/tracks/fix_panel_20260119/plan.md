# Implementation Plan - Fix Panel Positioning and Drag Usability

## Phase 1: Positioning & Visibility Reinforcement
- [x] Task: Write verification tests for `#jrpd-marker-container` CSS properties (position: fixed, z-index).
- [x] Task: Ensure `position: fixed` is correctly applied and not overridden by parent contexts or YouTube CSS.
- [x] Task: Increase `z-index` to a maximum value (e.g., 2147483647) to prevent obstruction by YouTube headers.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Positioning & Visibility Reinforcement' (Protocol in workflow.md) [checkpoint: 2b105e7]

## Phase 2: Enhanced Drag Logic
- [x] Task: Write tests for the new "Drag-Anywhere" logic, ensuring clicks on buttons are ignored.
- [x] Task: Move mouse event listeners from the header (`title`) to the main `container`.
- [x] Task: Update the `onmousedown` logic to check `e.target` and prevent dragging when interactive elements (buttons, icons) are clicked.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Enhanced Drag Logic' (Protocol in workflow.md)
