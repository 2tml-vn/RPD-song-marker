# Track Specification - Fix Panel Positioning and Drag Usability

## Overview
The user is experiencing two related UX issues with the JRPD Marker panel:
1.  **Scrolling:** The panel moves away when scrolling (likely due to incorrect positioning context or collision with other elements), instead of staying floating in view.
2.  **Unreachable Handle:** The header (drag handle) sometimes gets stuck behind other page elements (like the YouTube navbar), making it impossible to move the panel.

## Objectives
- **Ensure Visibility:** The panel must stay fixed in the user's viewport regardless of page scrolling (`position: fixed` reinforcement).
- **Improve Moveability:** Allow the user to drag the panel by clicking and holding **anywhere** on the container, not just the header. This eliminates the "unreachable handle" problem.

## Functional Requirements
- **Positioning:**
    - The main container `#jrpd-marker-container` must strictly use `position: fixed`.
    - It should maintain its position relative to the browser window, not the document flow.
- **Drag Logic:**
    - The drag event listener must be moved or expanded from the `title` element to the main `container` element.
    - Dragging must work regardless of where the user clicks inside the panel (background, empty space).
    - *Exception:** Clicking buttons or interactive elements (Mark, Undo, etc.) should *not* trigger a drag.

## Acceptance Criteria
- [ ] Scrolling the YouTube page does NOT cause the panel to scroll away; it stays floating in the same spot on the screen.
- [ ] Clicking and dragging the *body* of the panel moves it successfully.
- [ ] Clicking buttons still triggers their actions without moving the panel.
- [ ] The panel is movable even if the header is technically visually obstructed.
