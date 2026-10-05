// JRPD Results Review Panel
// Handles results display, editing, and playback controls

let reviewFontSize = 11;
const PREFS_KEY = "jrpd-review-prefs";

// Cache for parentheses exceptions (song names that should NOT have parentheses stripped)
let parenExceptionsCache = null;

/**
 * Fetch the list of song names that should preserve their parentheses.
 * Results are cached to avoid redundant API calls.
 * @returns {Promise<Set<string>>} Set of song names that should keep parentheses
 */
async function fetchParenExceptions() {
    if (parenExceptionsCache !== null) {
        return parenExceptionsCache;
    }
    try {
        const response = await fetch("http://127.0.0.1:5000/paren_exceptions");
        if (response.ok) {
            const exceptions = await response.json();
            parenExceptionsCache = new Set(exceptions);
            console.log("JRPD: Loaded", parenExceptionsCache.size, "parentheses exceptions");
        } else {
            parenExceptionsCache = new Set();
        }
    } catch (e) {
        console.warn("JRPD: Failed to fetch parentheses exceptions:", e);
        parenExceptionsCache = new Set();
    }
    return parenExceptionsCache;
}

function loadPanelPrefs() {
    try {
        const raw = localStorage.getItem(PREFS_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) {}
    return {};
}

function toggleHeartMark(ts) {
    if (heartMarkedTimestamps.has(ts)) {
        heartMarkedTimestamps.delete(ts);
    } else {
        heartMarkedTimestamps.add(ts);
    }
    saveHeartMarkedTimestamps();
    updateHeartButtonState(ts);
}

function updateHeartButtonState(ts) {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return;
    const row = list.querySelector(`[data-row-ts="${ts}"]`);
    if (!row) return;
    const heartBtn = row.querySelector(".heartBtn");
    if (heartBtn) {
        const isMarked = heartMarkedTimestamps.has(ts);
        // Use DOM API instead of innerHTML to avoid Trusted Types policy violation
        heartBtn.textContent = "";
        const span = document.createElement("span");
        span.style.color = isMarked ? "#ff5252" : "#666";
        span.textContent = isMarked ? "♥" : "♡";
        heartBtn.appendChild(span);
        heartBtn.title = isMarked ? "Remove heart mark" : "Add heart mark";
    }
}

function loadHeartMarkedTimestamps() {
    try {
        const raw = localStorage.getItem(PREFS_KEY);
        if (raw) {
            const prefs = JSON.parse(raw);
            if (prefs.heartMarkedTimestamps && Array.isArray(prefs.heartMarkedTimestamps)) {
                heartMarkedTimestamps = new Set(prefs.heartMarkedTimestamps);
            }
        }
    } catch (e) {}
}

function saveHeartMarkedTimestamps() {
    try {
        const prefs = loadPanelPrefs();
        prefs.heartMarkedTimestamps = Array.from(heartMarkedTimestamps);
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {
        console.error("JRPD: Failed to save heart marks:", e);
    }
}

function savePanelPrefs(updates) {
    try {
        const prefs = loadPanelPrefs();
        Object.assign(prefs, updates);
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {
        console.error("JRPD: Failed to save prefs:", e);
    }
}

function createResultsPanel() {
    if (document.getElementById("jrpd-results-panel")) return;

    const prefs = loadPanelPrefs();
    if (prefs.fontSize) reviewFontSize = prefs.fontSize;
    loadHeartMarkedTimestamps();

    const panel = document.createElement("div");
    panel.id = "jrpd-results-panel";
    panel.style.cssText = "position: fixed; min-width: 280px; min-height: 200px; background: #1a1a2e; color: #eee; z-index: 9999; padding: 0; border-radius: 10px; box-shadow: 0 4px 24px rgba(0,0,0,0.6); display: none; flex-direction: column; font-family: Roboto, Arial, sans-serif; border: 1px solid #333; resize: both; overflow: hidden;";

    const savedWidth = prefs.width || 400;
    const savedHeight = prefs.height || 400;
    const savedLeft = prefs.left;
    const savedTop = prefs.top || 80;

    panel.style.width = savedWidth + "px";
    panel.style.height = savedHeight + "px";
    
    if (savedLeft != null) {
        panel.style.left = savedLeft + "px";
        panel.style.top = savedTop + "px";
        panel.style.right = "auto";
    } else {
        panel.style.top = "80px";
        panel.style.right = "20px";
    }

    // Header (draggable)
    const header = document.createElement("div");
    header.style.cssText = "font-weight: bold; padding: 8px 12px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; background: #16213e; border-radius: 10px 10px 0 0; cursor: grab; user-select: none; flex-shrink: 0;";

    const title = document.createElement("span");
    title.textContent = "📋 Results Review";
    title.style.fontSize = "13px";
    header.appendChild(title);

    const controlsGroup = document.createElement("div");
    controlsGroup.style.cssText = "display: flex; gap: 5px; align-items: center;";

    // Font size dropdown
    const fontSelect = document.createElement("select");
    fontSelect.title = "Font size";
    fontSelect.style.cssText = "padding: 1px 2px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; font-size: 11px; cursor: pointer;";
    [9, 10, 11, 12, 14, 16].forEach(sz => {
        const opt = document.createElement("option");
        opt.value = sz;
        opt.textContent = sz + "px";
        if (sz === reviewFontSize) opt.selected = true;
        fontSelect.appendChild(opt);
    });
    fontSelect.onchange = () => {
        reviewFontSize = parseInt(fontSelect.value);
        const list = document.getElementById("jrpd-results-list");
        if (list) list.style.fontSize = reviewFontSize + "px";
        savePanelPrefs({ fontSize: reviewFontSize });
    };
    controlsGroup.appendChild(fontSelect);
    
    const copyBtn = document.createElement("button");
    copyBtn.textContent = "📋";
    copyBtn.title = "Copy results to clipboard";
    copyBtn.style.cssText = "padding: 2px 6px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; cursor: pointer; font-size: 13px;";
    copyBtn.onclick = () => {
        const list = document.getElementById("jrpd-results-list");
        if (!list) return;
        
        // Get all text content from the results list
        const lines = [];
        list.querySelectorAll("[data-result-row]").forEach(row => {
            // Get timestamp - the tsSpan is the first/only span with monospace font
            const tsSpan = row.querySelector("span.tsSpan");
            if (tsSpan) {
                const ts = tsSpan.textContent.trim();
                let content = "";
                
                // Check if this is a gap row (has gapLabel)
                const gapLabel = row.querySelector(".gapLabel");
                if (gapLabel) {
                    content = "";
                }
                // Otherwise it's a song row - get the song text from the songContainer
                else {
                    const songContainer = row.querySelector(".songContainer");
                    if (songContainer) {
                        // Get the song span (the one with the title attribute containing the full song string)
                        const songSpan = songContainer.querySelector("span[title]");
                        if (songSpan) {
                            content = songSpan.textContent.trim();
                        } else {
                            // Fallback: get any span inside songContainer that's not the edit button
                            const spans = songContainer.querySelectorAll("span");
                            for (const span of spans) {
                                if (!span.textContent.includes('✏️')) {
                                    content = span.textContent.trim();
                                    break;
                                }
                            }
                        }
                    }
                }
                
                // Check if this row is heart-marked (get ts from row's data attribute)
                const rowTs = row.getAttribute("data-row-ts");
                const isHeartMarked = heartMarkedTimestamps.has(rowTs);
                const heartPrefix = isHeartMarked ? "♥ " : "";
                
                if (content) {
                    lines.push(`${heartPrefix}${ts} ${content}`);
                } else {
                    lines.push(heartPrefix + ts);
                }
            }
        });
        
        const textToCopy = lines.join("\n");
        navigator.clipboard.writeText(textToCopy).then(() => {
            showToast("Results copied to clipboard!", "#4caf50");
            // Close the panel after copying (without opening Notepad++)
            panel.style.display = "none";
            isReviewMode = false;
            hideSongPanels();
            fetch("http://127.0.0.1:5000/close_review").catch(() => {});
        }).catch(err => {
            console.error("JRPD: Failed to copy text: ", err);
            showToast("Failed to copy results", "#f44336");
        });
    };
    controlsGroup.appendChild(copyBtn);
    
    const reloadBtn = document.createElement("button");
    reloadBtn.textContent = "↻";
    reloadBtn.title = "Reload results.txt";
    reloadBtn.style.cssText = "padding: 2px 6px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; cursor: pointer; font-size: 13px;";
    reloadBtn.onclick = () => { reviewLastMtime = 0; fetchResultsFile(); };
    controlsGroup.appendChild(reloadBtn);

    const doneBtn = document.createElement("button");
    doneBtn.textContent = "Done";
    doneBtn.style.cssText = "padding: 2px 8px; background: #2e7d32; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; font-weight: bold;";
    doneBtn.onclick = () => {
        savePanelPrefs({ 
            width: panel.offsetWidth, 
            height: panel.offsetHeight,
            left: panel.offsetLeft, 
            top: panel.offsetTop 
        });
        reviewLoopActive = false;
        reviewActiveGapTs = null;
        currentGapStart = -1;
        currentGapEnd = -1;
        panel.style.display = "none";
        isReviewMode = false;
        hideSongPanels();
        fetch("http://127.0.0.1:5000/review_done").catch(() => {});
    };
    controlsGroup.appendChild(doneBtn);
    header.appendChild(controlsGroup);
    panel.appendChild(header);

    // Drag logic
    let isDragging = false, dragOffX = 0, dragOffY = 0;
    header.addEventListener("mousedown", (e) => {
        if (e.target.tagName === "BUTTON" || e.target.tagName === "SELECT" || e.target.tagName === "OPTION") return;
        isDragging = true;
        dragOffX = e.clientX - panel.offsetLeft;
        dragOffY = e.clientY - panel.offsetTop;
        header.style.cursor = "grabbing";
        e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        panel.style.left = (e.clientX - dragOffX) + "px";
        panel.style.top = (e.clientY - dragOffY) + "px";
        panel.style.right = "auto";
    });
    document.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            header.style.cursor = "grab";
            savePanelPrefs({ left: panel.offsetLeft, top: panel.offsetTop });
        }
    });

    // Resize detection
    let resizeTimer = null;
    if (typeof ResizeObserver !== "undefined") {
        new ResizeObserver(() => {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                const w = panel.offsetWidth;
                const h = panel.offsetHeight;
                if (w > 0 && h > 0) savePanelPrefs({ width: w, height: h });
            }, 500);
        }).observe(panel);
    }

    // List Container
    const list = document.createElement("div");
    list.id = "jrpd-results-list";
    list.style.cssText = "overflow-y: auto; flex-grow: 1; padding: 8px 10px; font-size: " + reviewFontSize + "px;";
    panel.appendChild(list);

    document.body.appendChild(panel);
}

function parseResultsLine(line) {
    const match = line.match(/^(\d+:\d{2}(?::\d{2})?)\s?(.*)/);
    if (!match) return null;
    return { ts: match[1], song: (match[2] || "").trim() };
}

function fetchResultsFile(options = {}) {
    const { forceFullRender = false, preserveScroll = true } = options;
    fetch("http://127.0.0.1:5000/results_file")
    .then(r => r.json())
    .then(data => {
        // DEBUG: Log the received data
        console.log("JRPD: [DEBUG] fetchResultsFile received data:", data);
        console.log("JRPD: [DEBUG] Number of lines:", data.lines ? data.lines.length : 0);
        console.log("JRPD: [DEBUG] mtime:", data.mtime, "reviewLastMtime:", reviewLastMtime);
        if (data.mtime && data.mtime === reviewLastMtime) return;
        reviewLastMtime = data.mtime || 0;
        renderResultsPanel(data.lines || [], { forceFullRender, preserveScroll });
    })
    .catch(e => console.error("JRPD: Failed to fetch results_file", e));
}

/**
 * Update a single result row without full re-render.
 * @param {string} timestamp - The timestamp of the row to update
 * @param {string} newSong - The new song text
 * @returns {boolean} True if update was successful
 */
function updateSingleResultRow(timestamp, newSong) {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return false;
    
    const row = list.querySelector(`[data-row-ts="${timestamp}"]`);
    if (!row) return false;
    
    const wasGap = row.querySelector(".gapLabel") !== null;
    const isNowGap = !newSong;
    
    // If gap status changed, we need to rebuild the row structure
    if (wasGap !== isNowGap) {
        return false; // Signal that full re-render is needed
    }
    
    if (isNowGap) {
        // Still a gap, nothing to update
        return true;
    }
    
    // Update song text
    const songContainer = row.querySelector(".songContainer");
    if (!songContainer) return false;
    
    const songSpan = songContainer.querySelector("span[title]");
    if (songSpan) {
        songSpan.textContent = newSong;
        songSpan.title = newSong;
    }
    
    // Update edit button handler with new song text
    const editBtn = songContainer.querySelector("button");
    if (editBtn) {
        // Clone and replace to remove old event listener
        const newEditBtn = editBtn.cloneNode(true);
        newEditBtn.onclick = (e) => {
            e.stopPropagation();
            showEditSongFormForRow(timestamp, newSong);
        };
        editBtn.parentNode.replaceChild(newEditBtn, editBtn);
    }
    
    return true;
}

/**
 * Create a result row element.
 * @param {Object} entry - The entry object with ts and song properties
 * @param {number} idx - The index in the parsed array
 * @param {Array} parsed - The full parsed array (for next timestamp lookup)
 * @returns {HTMLElement} The row element
 */
function createResultRow(entry, idx, parsed) {
    const isGap = !entry.song;
    const row = document.createElement("div");
    row.setAttribute("data-result-row", "1");
    row.setAttribute("data-row-ts", entry.ts);
    const rowBg = isGap ? "background: #2a1a1a; border-left: 3px solid #ff5252;" : "background: #1e1e30;";
    row.style.cssText = `padding: 4px 8px; margin-bottom: 2px; border-radius: 5px; font-size: ${reviewFontSize}px; display: flex; align-items: center; gap: 6px; cursor: pointer; transition: outline 0.15s; min-height: 24px; ${rowBg}`;

    if (reviewSelectedTs === entry.ts) {
        row.style.outline = "2px solid #ffeb3b";
        row.style.outlineOffset = "-1px";
    }

    row.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON") return;
        const list = document.getElementById("jrpd-results-list");
        if (reviewSelectedTs === entry.ts) {
            hideSongPanels();
            return;
        }
        list.querySelectorAll("[data-result-row]").forEach(r => { r.style.outline = "none"; });
        row.style.outline = "2px solid #ffeb3b";
        row.style.outlineOffset = "-1px";
        showSongPanels(entry.ts);
    });

    // Play button
    const seekBtn = document.createElement("button");
    seekBtn.textContent = "▶";
    seekBtn.title = `Seek & loop ${entry.ts}`;
    const isActive = reviewActiveGapTs === entry.ts;
    const btnColor = isGap ? "#c62828" : "#0f3460";
    const btnActiveColor = isGap ? "#ff5252" : "#1a73e8";
    seekBtn.style.cssText = `padding: 1px 6px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; ${isActive ? `background: ${btnActiveColor}; color: white;` : `background: ${btnColor}; color: #ccc;`}`;
    seekBtn.setAttribute("data-gap-ts", entry.ts);
    seekBtn.onclick = () => {
        // Select the row and show song panels (same as clicking the row)
        const list = document.getElementById("jrpd-results-list");
        list.querySelectorAll("[data-result-row]").forEach(r => { r.style.outline = "none"; });
        row.style.outline = "2px solid #ffeb3b";
        row.style.outlineOffset = "-1px";
        showSongPanels(entry.ts);

        const startSec = parseTimestampToSeconds(entry.ts);
        const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
        if (!video) return;

        if (reviewActiveGapTs === entry.ts) {
            reviewLoopActive = false;
            reviewActiveGapTs = null;
            currentGapStart = -1;
            currentGapEnd = -1;
            updateReviewActiveButton(null);
            return;
        }

        video.currentTime = startSec;
        video.play();
        lastSeekTs = startSec;

        let endSec = video.duration;
        if (idx + 1 < parsed.length) {
            endSec = parseTimestampToSeconds(parsed[idx + 1].ts);
        }

        currentGapStart = startSec;
        currentGapEnd = endSec;
        reviewLoopActive = true;
        reviewActiveGapTs = entry.ts;
        updateReviewActiveButton(entry.ts);
        showToast(`Looping ${entry.ts}`, "#f57c00");
    };
    row.appendChild(seekBtn);

    // Heart button
    const heartBtn = document.createElement("button");
    const isHeartMarked = heartMarkedTimestamps.has(entry.ts);
    // Use DOM API instead of innerHTML to avoid Trusted Types policy violation
    const heartSpan = document.createElement("span");
    heartSpan.style.color = isHeartMarked ? "#ff5252" : "#666";
    heartSpan.textContent = isHeartMarked ? "♥" : "♡";
    heartBtn.appendChild(heartSpan);
    heartBtn.title = isHeartMarked ? "Remove heart mark" : "Add heart mark";
    heartBtn.className = "heartBtn";
    heartBtn.style.cssText = "padding: 1px 4px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: transparent;";
    heartBtn.onclick = (e) => {
        e.stopPropagation();
        toggleHeartMark(entry.ts);
    };
    row.appendChild(heartBtn);

    const tsSpan = document.createElement("span");
    tsSpan.className = "tsSpan";
    tsSpan.textContent = entry.ts;
    tsSpan.style.cssText = `font-family: monospace; flex-shrink: 0; min-width: 42px; font-size: 11px; ${isGap ? "color: #ff8a80; font-weight: bold;" : "color: #82b1ff;"}`;
    row.appendChild(tsSpan);

    if (isGap) {
        const gapLabel = document.createElement("span");
        gapLabel.className = "gapLabel";
        gapLabel.textContent = "(empty)";
        gapLabel.style.cssText = "color: #666; font-style: italic; font-size: 11px;";
        row.appendChild(gapLabel);
    } else {
        // Create container for song info and edit button
        const songContainer = document.createElement("div");
        songContainer.className = "songContainer";
        songContainer.style.cssText = "display: flex; align-items: flex-start; gap: 5px; flex-grow: 1;";

        const songSpan = document.createElement("span");
        songSpan.textContent = entry.song;
        songSpan.style.cssText = "color: #ccc; word-break: break-word; white-space: normal; font-size: inherit; flex-grow: 1;";
        songSpan.title = entry.song;
        songContainer.appendChild(songSpan);

        // Add edit button for existing songs
        const editBtn = document.createElement("button");
        editBtn.textContent = "✏️";
        editBtn.title = "Edit song variables";
        editBtn.style.cssText = "padding: 2px 4px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 10px; flex-shrink: 0;";
        editBtn.onclick = (e) => {
            e.stopPropagation(); // Prevent triggering the main row click
            showEditSongFormForRow(entry.ts, entry.song);
        };
        songContainer.appendChild(editBtn);

        row.appendChild(songContainer);
    }
    
    return row;
}

function renderResultsPanel(lines, options = {}) {
    const { forceFullRender = false, preserveScroll = true } = options;
    const list = document.getElementById("jrpd-results-list");
    if (!list) {
        console.log("JRPD: [DEBUG] renderResultsPanel - list element not found");
        return;
    }
    
    // DEBUG: Log input lines
    console.log("JRPD: [DEBUG] renderResultsPanel called with", lines.length, "lines");
    if (lines.length > 0) {
        console.log("JRPD: [DEBUG] First line:", lines[0]);
    }
    
    const parsed = lines.map(l => parseResultsLine(l)).filter(Boolean);
    
    // DEBUG: Log parsed results
    console.log("JRPD: [DEBUG] Parsed", parsed.length, "entries");
    if (parsed.length > 0) {
        console.log("JRPD: [DEBUG] First parsed entry:", parsed[0]);
    }
    
    // Save scroll position before any modifications
    const savedScrollTop = list.scrollTop;
    
    // Try incremental update if not forced
    if (!forceFullRender) {
        const existingRows = list.querySelectorAll("[data-result-row]");
        
        // Check if we can do incremental update (same number of rows)
        if (existingRows.length === parsed.length) {
            let needsFullRebuild = false;
            
            // First pass: check if timestamps match
            existingRows.forEach((row, idx) => {
                if (row.getAttribute("data-row-ts") !== parsed[idx].ts) {
                    needsFullRebuild = true;
                }
            });
            
            if (!needsFullRebuild) {
                // Second pass: try to update each row in place
                existingRows.forEach((row, idx) => {
                    const entry = parsed[idx];
                    const wasGap = row.querySelector(".gapLabel") !== null;
                    const isNowGap = !entry.song;
                    
                    // If gap status changed, mark for full rebuild
                    if (wasGap !== isNowGap) {
                        needsFullRebuild = true;
                        return;
                    }
                    
                    // Update song text if not a gap
                    if (!isNowGap) {
                        const songSpan = row.querySelector(".songContainer span[title]");
                        if (songSpan && songSpan.textContent !== entry.song) {
                            songSpan.textContent = entry.song;
                            songSpan.title = entry.song;
                        }
                    }
                });
                
                if (!needsFullRebuild) {
                    // Restore scroll position and return
                    if (preserveScroll) {
                        list.scrollTop = savedScrollTop;
                    }
                    return; // Done, no full rebuild needed
                }
            }
        }
    }
    
    // Full rebuild needed
    list.textContent = "";

    parsed.forEach((entry, idx) => {
        const row = createResultRow(entry, idx, parsed);
        list.appendChild(row);
    });

    // Restore scroll position after rebuild
    if (preserveScroll) {
        list.scrollTop = savedScrollTop;
    }
}

function updateReviewActiveButton(activeTs) {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return;
    list.querySelectorAll("button[data-gap-ts]").forEach(btn => {
        const ts = btn.getAttribute("data-gap-ts");
        const row = btn.parentElement;
        const isGapRow = row && row.style.borderLeft.includes("ff5252");
        if (ts === activeTs) {
            btn.style.background = isGapRow ? "#ff5252" : "#1a73e8";
            btn.style.color = "white";
        } else {
            btn.style.background = isGapRow ? "#c62828" : "#0f3460";
            btn.style.color = "#ccc";
        }
    });
}

async function showEditSongFormForRow(timestamp, songDisplay) {
    // Parse the display string to extract current values
    const displayParts = songDisplay.split(" - ");
    const songPart = displayParts[0] || "";
    const artistPart = displayParts[1] || "";

    // Extract song key from display string
    // Format is typically: "original_song [(international)] - original_artist [(international_artist)]"
    let songKey = songPart.trim();
    // Remove any parentheses content to get the base song name
    // Exception: preserve parentheses for songs in the exceptions list
    const exceptions = await fetchParenExceptions();
    if (!exceptions.has(songKey)) {
        songKey = songKey.replace(/\s*\([^)]+\)\s*/g, '').trim();
    }
    
    // Create overlay modal for editing (show loading state)
    const overlay = document.createElement("div");
    overlay.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; display: flex; align-items: center; justify-content: center;";

    const modal = document.createElement("div");
    modal.style.cssText = "background: #2a2a3e; color: #eee; padding: 20px; border-radius: 10px; min-width: 400px; max-width: 600px; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.8);";

    const title = document.createElement("h3");
    title.textContent = `Edit Song: ${songKey}`;
    title.style.marginTop = "0";
    title.style.color = "#82b1ff";
    modal.appendChild(title);

    // Loading message while fetching data
    const loadingMsg = document.createElement("p");
    loadingMsg.textContent = "Loading song data...";
    loadingMsg.style.color = "#aaa";
    modal.appendChild(loadingMsg);

    // Buttons container (only cancel button initially)
    const buttonsDiv = document.createElement("div");
    buttonsDiv.style.cssText = "display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;";
    
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = "padding: 8px 16px; background: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;";
    cancelBtn.onclick = () => {
        document.body.removeChild(overlay);
    };
    buttonsDiv.appendChild(cancelBtn);
    modal.appendChild(buttonsDiv);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Fetch existing song data from server
    let songData = {};
    try {
        const response = await fetch(`http://127.0.0.1:5000/get_song_data?key=${encodeURIComponent(songKey)}`);
        if (response.ok) {
            songData = await response.json();
        } else {
            console.warn(`Failed to fetch song data: ${response.status}`);
        }
    } catch (e) {
        console.error("Error fetching song data:", e);
    }

    // Remove loading message
    document.body.removeChild(overlay);

    // Now build the actual form with fetched data
    const overlay2 = document.createElement("div");
    overlay2.style.cssText = overlay.style.cssText;
    const modal2 = document.createElement("div");
    modal2.style.cssText = modal.style.cssText;
    const title2 = document.createElement("h3");
    title2.textContent = `Edit Song: ${songKey}`;
    title2.style.marginTop = "0";
    title2.style.color = "#82b1ff";
    modal2.appendChild(title2);

    // Create form elements
    const form = document.createElement("form");
    form.style.cssText = "display: flex; flex-direction: column; gap: 10px;";

    // Song Key (readonly)
    const keyLabel = document.createElement("label");
    keyLabel.textContent = "Song Key:";
    keyLabel.style.fontWeight = "bold";
    form.appendChild(keyLabel);
    
    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.value = songKey;
    keyInput.readOnly = true;
    keyInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(keyInput);

    // Intl Name
    const intlLabel = document.createElement("label");
    intlLabel.textContent = "International Name:";
    form.appendChild(intlLabel);
    
    const intlInput = document.createElement("input");
    intlInput.type = "text";
    intlInput.value = songData.intl || "";
    intlInput.placeholder = "Enter international name";
    intlInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(intlInput);
    
    // Original Artist
    const artistOrigLabel = document.createElement("label");
    artistOrigLabel.textContent = "Original Artist:";
    form.appendChild(artistOrigLabel);
    
    const artistOrigInput = document.createElement("input");
    artistOrigInput.type = "text";
    artistOrigInput.value = songData.artist_orig || "";
    artistOrigInput.placeholder = "Enter original artist";
    artistOrigInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(artistOrigInput);
    
    // International Artist
    const artistIntlLabel = document.createElement("label");
    artistIntlLabel.textContent = "International Artist:";
    form.appendChild(artistIntlLabel);
    
    const artistIntlInput = document.createElement("input");
    artistIntlInput.type = "text";
    artistIntlInput.value = songData.artist_intl || "";
    artistIntlInput.placeholder = "Enter international artist";
    artistIntlInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(artistIntlInput);

    // Remap field
    const remapLabel = document.createElement("label");
    remapLabel.textContent = "Remap to (optional):";
    form.appendChild(remapLabel);
    
    const remapInput = document.createElement("input");
    remapInput.type = "text";
    remapInput.value = songData.remap || "";
    remapInput.placeholder = "Enter target song name for remapping";
    remapInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 15px;";
    remapInput.title = "If set, this song name will be automatically remapped to the specified target on next identification (moves to false_maps.json)";
    form.appendChild(remapInput);
    
    // Buttons container
    const buttonsDiv2 = document.createElement("div");
    buttonsDiv2.style.cssText = "display: flex; gap: 10px; justify-content: flex-end;";
    
    const saveBtn = document.createElement("button");
    saveBtn.type = "submit";
    saveBtn.textContent = "Save Changes";
    saveBtn.style.cssText = "padding: 8px 16px; background: #2e7d32; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;";
    
    const cancelBtn2 = document.createElement("button");
    cancelBtn2.type = "button";
    cancelBtn2.textContent = "Cancel";
    cancelBtn2.style.cssText = "padding: 8px 16px; background: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;";
    cancelBtn2.onclick = () => {
        document.body.removeChild(overlay2);
    };
    
    buttonsDiv2.appendChild(cancelBtn2);
    buttonsDiv2.appendChild(saveBtn);
    form.appendChild(buttonsDiv2);
    
    form.onsubmit = (e) => {
        e.preventDefault();
    
        // Prepare form data for POST request
        const params = new URLSearchParams();
        params.append('key', songKey);
        params.append('intl', intlInput.value.trim());
        params.append('artist_orig', artistOrigInput.value.trim());
        params.append('artist_intl', artistIntlInput.value.trim());
        params.append('remap', remapInput.value.trim());
    
        // DEBUG: Log what's being sent
        console.log("JRPD: [DEBUG] Sending update_song_vars request (from results panel)");
        console.log("JRPD: [DEBUG] songKey:", songKey);
        console.log("JRPD: [DEBUG] intl:", intlInput.value.trim());
        console.log("JRPD: [DEBUG] artist_orig:", artistOrigInput.value.trim());
        console.log("JRPD: [DEBUG] artist_intl:", artistIntlInput.value.trim());
        console.log("JRPD: [DEBUG] remap:", remapInput.value.trim());
        console.log("JRPD: [DEBUG] params:", params.toString());
    
        fetch('http://127.0.0.1:5000/update_song_vars', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: params
        })
        .then(r => r.json())
        .then(res => {
            if (res.status === "ok") {
                showToast(`Updated song: ${songKey}`, "#2e7d32");
                // Close modal and refresh the results
                document.body.removeChild(overlay2);
                reviewLastMtime = 0;
                fetchResultsFile(); // Refresh the results panel to show updated values
            } else {
                showToast("Update failed: " + (res.msg || "unknown error"), "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: update_song_vars failed", e);
            showToast("Update failed", "#c62828");
            document.body.removeChild(overlay2);
        });
    };
    
    modal2.appendChild(form);
    overlay2.appendChild(modal2);
    document.body.appendChild(overlay2);
}