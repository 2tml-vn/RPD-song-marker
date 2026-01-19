# Product Guidelines - JRPD Live Marker Pro

## Documentation & Tone
- **Direct & Concise:** All documentation and CLI output must be minimalist and to the point.
- **Immediate Feedback:** User actions in the browser must trigger immediate visual confirmation (toasts).

## UI/UX Standards (Userscript)
- **Modern Polish:** Maintain a high-quality visual experience using glassmorphism (backdrop filters), rounded corners (16px), and smooth transitions.
- **Unobtrusive Docking:** The UI should be capable of docking to screen corners to remain visible without interfering with the video content.

## Data Processing & Resilience
- **Fail-Safe Acquisition:** Audio downloads must be strictly validated against source duration. Truncated files must be automatically detected and redownloaded.
- **Silent Robustness:** The backend should automatically retry transient errors (network, temporary blocks) without bothering the user.
- **Explicit Failure States:** Markers that cannot be identified after all attempts must be explicitly labeled ("Unidentified") to prevent processing loops.

## Content Standards
- **Japanese Localization:** Prioritize Japanese song titles and artist names.
- **Artist Filtering:** Discard artist names that exceed 60 characters to maintain clean, readable tracklists (common for large collaboration casts).
- **Preferred Mapping:** Respect custom mapping dictionaries to override automated results with preferred localized titles.

## Code Quality
- **Cross-Platform Compatibility:** Ensure scripts handle platform-specific encoding (UTF-8) and file paths (Windows/Linux) correctly.
- **State Integrity:** Use structured data formats (JSON) for project state to allow for reliable resuming and data recovery.
