# Track Specification - Optimal Dynamic Sliding Window

## Overview
Implement a mathematically proportional "Dynamic Slide" strategy for song identification. The search window will always be 12 seconds (Shazam's optimal size) and will slide across the available gap to ensure 100% coverage with minimal attempts.

## Objectives
- **Total Coverage:** Ensure every second of the gap is scanned by at least one 12s window.
- **Efficiency:** Calculate the minimum number of attempts needed to cover the gap while maintaining a safety overlap.
- **Boundary Precision:** Ensure windows are perfectly distributed from the marker start to the next marker start.

## Functional Requirements
- **Gap Calculation:** `GapSize = NextMarker - CurrentMarker`.
- **Attempt Scaling (N):**
    - If `GapSize <= 12`: `N = 1`.
    - If `GapSize > 12`: `N = clamp(ceil(GapSize / 10), 2, 10)`.
- **Step Calculation (S):**
    - If `N > 1`: `Step = (GapSize - 12) / (N - 1)`.
    - Else: `Step = 0`.
- **The Slide Loop:**
    - For `i` from `0` to `N-1`:
        - `CurrentStartOffset = i * Step`
        - `CurrentDuration = 12` (or `GapSize` if total gap is < 12)
        - Execute FFmpeg cut and Shazam identification.
- **Immediate Exit:** Stop retrying as soon as a match is found.

## Acceptance Criteria
- [ ] A 19s gap generates exactly 2 attempts (Start 0s, Start 7s).
- [ ] A 25s gap generates exactly 3 attempts (Start 0s, Start 6.5s, Start 13s).
- [ ] No attempt ever exceeds the boundary of the next marker.
- [ ] Large gaps (e.g., 2 mins) are covered by 10 evenly spaced 12s windows.
