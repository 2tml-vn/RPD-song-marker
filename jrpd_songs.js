/**
 * JRPD Song List Side Panels
 * Unified panel for misidentified, missed, and songs database with color-coded categories
 * @module jrpd_songs
 * @requires jrpd_utils
 * @requires jrpd_state
 */

// NOTE: songListsCache and songListsLoading are defined in jrpd_state.js

/** Panel collapse state (persisted in localStorage) */
const PANEL_PREFS_KEY = "jrpd-panel-prefs";
let panelCollapsedState = { unified: false };

/** Category color definitions */
const CATEGORY_COLORS = {
misident: { color: '#c62828', border: '#ef5350', icon: '⚠️', name: 'Misidentified' },
missed: { color: '#f57f17', border: '#ffca28', icon: '❌', name: 'Missed' },
songs: { color: '#2e7d32', border: '#66bb6a', icon: '🎵', name: 'Database' }
};

/**
* Build a song display string from components.
* Format: "song [(intl)] - artist [(artist_intl)]"
* @param {string} key - The song key/name
* @param {string} [intl] - International name
* @param {string} [artist] - Artist name
* @param {string} [artistIntl] - International artist name
* @returns {string} The formatted display string
*/
function buildSongDisplay(key, intl, artist, artistIntl) {
    let display = key;
    if (intl) display += ` (${intl})`;
    if (artist) {
        display += ` - ${artist}`;
        if (artistIntl) display += ` (${artistIntl})`;
    }
    return display;
}

/**
* Load panel collapse preferences from localStorage.
 * Migrates old format to new unified format if needed.
 * @returns {void}
 */
function loadPanelCollapsePrefs() {
    try {
        const raw = localStorage.getItem(PANEL_PREFS_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            // Check if old format (with misident/missed/songs keys)
            if (parsed.misident || parsed.missed || parsed.songs) {
                // Migrate old format to new unified format
                // Use the most collapsed state or default to false
                panelCollapsedState.unified = parsed.misident || parsed.missed || parsed.songs || false;
                
                // Update localStorage with new format
                localStorage.setItem(PANEL_PREFS_KEY, JSON.stringify(panelCollapsedState));
            } else {
                // New format already
                panelCollapsedState = parsed;
            }
        }
    } catch (e) {}
}

/**
 * Save panel collapse preferences to localStorage.
 * @returns {void}
 */
function savePanelCollapsePrefs() {
    try {
        localStorage.setItem(PANEL_PREFS_KEY, JSON.stringify(panelCollapsedState));
    } catch (e) {}
}

/**
 * Create the song list panels if they don't exist.
 * Sets up the unified panel with header, content, and add song section.
 * @returns {void}
 */
function createSongListPanels() {
    if (document.getElementById("jrpd-unified-panel")) return;

    loadPanelCollapsePrefs();

    const panelStyle = "position: fixed; top: 80px; width: 400px; height: 60vh; min-width: 250px; min-height: 200px; color: #eee; z-index: 9998; padding: 0; border-radius: 10px; box-shadow: 0 4px 24px rgba(0,0,0,0.6); display: none; flex-direction: column; font-family: Roboto, Arial, sans-serif; border: 1px solid #333; overflow: hidden;";

    // Unified Songs Panel
    const unifiedPanel = document.createElement("div");
    unifiedPanel.id = "jrpd-unified-panel";
    unifiedPanel.setAttribute("data-panel-type", "unified");
    unifiedPanel.style.cssText = panelStyle + " background: #1e1e2e;";
    
    const unifiedHeader = createPanelHeader("🎵 All Song Lists", "unified", "#2a2a3e");
    unifiedPanel.appendChild(unifiedHeader);

    const unifiedContent = createPanelContent("unified", "#1e1e2e");
    unifiedPanel.appendChild(unifiedContent);
    document.body.appendChild(unifiedPanel);

    // Add song input section (created once during panel creation)
    addSongInputSection();

    // Apply initial collapse state
    applyCollapseState("unified", panelCollapsedState.unified);
}

/**
 * Create a panel header element with title and controls.
 * @param {string} title - The header title text
 * @param {string} panelType - The panel type identifier
 * @param {string} bgColor - Background color for the header
 * @returns {HTMLElement} The header element
 */
function createPanelHeader(title, panelType, bgColor) {
    const header = document.createElement("div");
    header.style.cssText = `font-weight: bold; padding: 8px 12px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; background: ${bgColor}; border-radius: 10px 10px 0 0; cursor: pointer; user-select: none; flex-shrink: 0;`;
    
    const titleSpan = document.createElement("span");
    titleSpan.textContent = title;
    titleSpan.style.fontSize = "12px";
    header.appendChild(titleSpan);

    const controlsGroup = document.createElement("div");
    controlsGroup.style.cssText = "display: flex; gap: 5px; align-items: center;";

    // Collapse/Expand toggle button
    const toggleBtn = document.createElement("button");
    toggleBtn.className = "jrpd-panel-toggle";
    toggleBtn.setAttribute("data-panel-type", panelType);
    toggleBtn.textContent = panelCollapsedState[panelType] ? "▶" : "▼";
    toggleBtn.title = panelCollapsedState[panelType] ? "Expand panel" : "Collapse panel";
    toggleBtn.style.cssText = "padding: 1px 6px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 10px;";
    toggleBtn.onclick = (e) => {
        e.stopPropagation();
        togglePanelCollapse(panelType);
    };
    controlsGroup.appendChild(toggleBtn);

    // Close button
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.style.cssText = "padding: 1px 6px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 12px;";
    closeBtn.onclick = () => hideSongPanels();
    controlsGroup.appendChild(closeBtn);

    header.appendChild(controlsGroup);
    
    // Double-click header to toggle collapse
    header.ondblclick = () => togglePanelCollapse(panelType);
    
    return header;
}

/**
 * Create panel content with search, list, and add song section.
 * @param {string} panelType - The panel type identifier
 * @param {string} bgColor - Background color for the content
 * @returns {HTMLElement} The content element
 */
function createPanelContent(panelType, bgColor) {
    const content = document.createElement("div");
    content.className = "jrpd-panel-content";
    content.style.cssText = "display: flex; flex-direction: column; flex-grow: 1; overflow: hidden;";

    const search = document.createElement("input");
    search.id = `jrpd-${panelType}-search`;
    search.type = "text";
    search.placeholder = "Search all song lists...";
    search.style.cssText = `width: 100%; box-sizing: border-box; padding: 6px 8px; margin: 0; background: ${bgColor}; color: white; border: none; border-bottom: 1px solid #333; font-size: 12px;`;
    search.addEventListener("input", () => filterSongPanel(search.value));
    content.appendChild(search);

    const list = document.createElement("div");
    list.id = `jrpd-${panelType}-list`;
    list.style.cssText = "overflow-y: auto; flex-grow: 1; padding: 6px 8px;";
    content.appendChild(list);

    // Add song input section container (fixed position, not scrollable)
    const addSongContainer = document.createElement("div");
    addSongContainer.id = `jrpd-${panelType}-add-song-container`;
    addSongContainer.style.cssText = "flex-shrink: 0; padding: 8px; background: #1a1a28; border-top: 1px solid #333;";
    content.appendChild(addSongContainer);

    // Add category legend
    const legend = document.createElement("div");
    legend.className = "jrpd-category-legend";
    legend.style.cssText = "padding: 8px; background: #151520; border-top: 1px solid #333; font-size: 10px; display: flex; justify-content: space-around; flex-shrink: 0;";
    
    Object.entries(CATEGORY_COLORS).forEach(([cat, info]) => {
        const legendItem = document.createElement("div");
        legendItem.style.cssText = "display: flex; align-items: center; gap: 4px; color: #aaa;";
        
        const iconSpan = document.createElement("span");
        iconSpan.textContent = info.icon;
        iconSpan.style.color = info.color;
        legendItem.appendChild(iconSpan);
        
        const nameSpan = document.createElement("span");
        nameSpan.textContent = info.name;
        legendItem.appendChild(nameSpan);
        
        legend.appendChild(legendItem);
    });
    
    content.appendChild(legend);

    return content;
}

/**
 * Toggle panel collapse state.
 * @param {string} panelType - The panel type to toggle
 * @returns {void}
 */
function togglePanelCollapse(panelType) {
    panelCollapsedState[panelType] = !panelCollapsedState[panelType];
    savePanelCollapsePrefs();
    applyCollapseState(panelType, panelCollapsedState[panelType]);
    positionSongPanels();
}

/**
 * Apply collapse state to a panel.
 * @param {string} panelType - The panel type
 * @param {boolean} collapsed - Whether the panel should be collapsed
 * @returns {void}
 */
function applyCollapseState(panelType, collapsed) {
    const panel = document.getElementById(`jrpd-${panelType}-panel`);
    if (!panel) return;

    const content = panel.querySelector(".jrpd-panel-content");
    const toggleBtn = panel.querySelector(".jrpd-panel-toggle");

    if (collapsed) {
        if (content) content.style.display = "none";
        panel.style.height = "auto";
        panel.style.minHeight = "unset";
        if (toggleBtn) {
            toggleBtn.textContent = "▶";
            toggleBtn.title = "Expand panel";
        }
    } else {
        if (content) content.style.display = "flex";
        panel.style.height = "60vh";
        panel.style.minHeight = "200px";
        if (toggleBtn) {
            toggleBtn.textContent = "▼";
            toggleBtn.title = "Collapse panel";
        }
    }
}

/**
 * Position the song panels relative to the results panel.
 * @returns {void}
 */
function positionSongPanels() {
    const resultsPanel = document.getElementById("jrpd-results-panel");
    const unifiedPanel = document.getElementById("jrpd-unified-panel");
    if (!resultsPanel || !unifiedPanel) return;

    const rRect = resultsPanel.getBoundingClientRect();
    const panelW = 400;
    const gap = 10;

    const isCollapsed = panelCollapsedState["unified"];
    const width = isCollapsed ? unifiedPanel.offsetWidth : panelW;
    
    unifiedPanel.style.top = rRect.top + "px";
    unifiedPanel.style.left = (rRect.left - gap - width) + "px";
    unifiedPanel.style.right = "auto";
    
    if (!isCollapsed) {
        unifiedPanel.style.height = rRect.height + "px";
    }
}

/**
 * Show the song panels for a specific timestamp.
 * @param {string} ts - The timestamp being reviewed
 * @returns {void}
 */
function showSongPanels(ts) {
    reviewSelectedTs = ts;
    createSongListPanels();
    positionSongPanels();

    const unifiedPanel = document.getElementById("jrpd-unified-panel");
    if (unifiedPanel) unifiedPanel.style.display = "flex";

    if (songListsCache) populateSongPanels(songListsCache);
    if (!songListsLoading) {
        songListsLoading = true;
        fetch("http://127.0.0.1:5000/song_lists")
            .then(r => r.json())
            .then(data => {
                songListsCache = data;
                songListsLoading = false;
                populateSongPanels(data);
            })
            .catch(e => {
                console.error("JRPD: Failed to fetch song_lists", e);
                songListsLoading = false;
            });
    }
}

/**
 * Hide all song panels and clear selection.
 * @returns {void}
 */
function hideSongPanels() {
    reviewSelectedTs = null;
    const unifiedPanel = document.getElementById("jrpd-unified-panel");
    if (unifiedPanel) unifiedPanel.style.display = "none";
    
    const unifiedSearch = document.getElementById("jrpd-unified-search");
    if (unifiedSearch) unifiedSearch.value = "";
    
    const list = document.getElementById("jrpd-results-list");
    if (list) {
        list.querySelectorAll("[data-result-row]").forEach(row => {
            row.style.outline = "none";
        });
    }
}

/**
 * Filter the song panel by search text.
 * @param {string} searchText - The search text to filter by
 * @returns {void}
 */
function filterSongPanel(searchText) {
    if (!songListsCache) return;
    
    const search = (searchText || "").toLowerCase();
    const list = document.getElementById("jrpd-unified-list");
    if (!list) return;
    
    // Combine all songs with category tags
    const allSongs = [
        ...(songListsCache.misidentified || []).map(s => ({...s, category: 'misident'})),
        ...(songListsCache.missed || []).map(s => ({...s, category: 'missed'})),
        ...(songListsCache.songs || []).map(s => ({...s, category: 'songs'}))
    ];
    
    // Filter by display name and category text
    const filtered = allSongs.filter(song => {
        const catInfo = CATEGORY_COLORS[song.category];
        const searchableText = `${song.display} ${catInfo.icon} ${catInfo.name}`.toLowerCase();
        return searchableText.includes(search);
    });
    
    list.textContent = "";
    filtered.forEach(song => {
        const item = createSongItem(song);
        list.appendChild(item);
    });
}

/**
 * Populate the song panels with data from the server.
 * @param {Object} data - The song lists data containing misidentified, missed, and songs arrays
 * @param {Array} [data.misidentified] - Array of misidentified songs
 * @param {Array} [data.missed] - Array of missed songs
 * @param {Array} [data.songs] - Array of songs from database
 * @returns {void}
 */
function populateSongPanels(data) {
    const unifiedList = document.getElementById("jrpd-unified-list");
    const unifiedSearch = document.getElementById("jrpd-unified-search");
    if (!unifiedList) return;

    if (unifiedSearch) unifiedSearch.value = "";

    // Combine all songs with category tags
    const allSongs = [
        ...(data.misidentified || []).map(s => ({...s, category: 'misident'})),
        ...(data.missed || []).map(s => ({...s, category: 'missed'})),
        ...(data.songs || []).map(s => ({...s, category: 'songs'}))
    ];

    unifiedList.textContent = "";
    allSongs.forEach(song => {
        unifiedList.appendChild(createSongItem(song));
    });
}

/**
 * Create a song item element for the list.
 * @param {Object} song - The song data
 * @param {string} song.key - The song key
 * @param {string} song.display - The display name
 * @param {string} [song.intl] - International name
 * @param {string} [song.artist_orig] - Original artist
 * @param {string} [song.artist_intl] - International artist
 * @param {string} song.category - The category (misident, missed, songs)
 * @returns {HTMLElement} The song item element
 */
function createSongItem(song) {
    const catInfo = CATEGORY_COLORS[song.category] || CATEGORY_COLORS['songs'];
    const item = document.createElement("div");
    item.style.cssText = `padding: 5px 8px; margin-bottom: 2px; background: rgba(255,255,255,0.05); cursor: pointer; border-radius: 4px; font-size: 11px; word-break: break-word; white-space: normal; transition: background 0.15s; display: flex; align-items: center; gap: 6px; border-left: 3px solid ${catInfo.color};`;
    
    // Category indicator badge
    const badgeSpan = document.createElement("span");
    badgeSpan.textContent = catInfo.icon;
    badgeSpan.style.cssText = `flex-shrink: 0; font-size: 12px; color: ${catInfo.color};`;
    item.appendChild(badgeSpan);
    
    const contentDiv = document.createElement("div");
    contentDiv.textContent = song.display;
    contentDiv.title = song.display;
    contentDiv.style.flexGrow = "1";
    item.appendChild(contentDiv);
    
    // Add edit button
    const editBtn = document.createElement("button");
    editBtn.textContent = "✏️";
    editBtn.title = "Edit song variables";
    editBtn.style.cssText = "padding: 2px 4px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 10px; flex-shrink: 0;";
    editBtn.onclick = (e) => {
        e.stopPropagation(); // Prevent triggering the main click event
        showEditSongForm(song.key, song.display, song.intl, song.artist_orig, song.artist_intl);
    };
    item.appendChild(editBtn);
    
    item.onmouseover = () => {
        item.style.background = `rgba(255,255,255,0.12)`;
        editBtn.style.background = "#555";
    };
    item.onmouseout = () => {
        item.style.background = "rgba(255,255,255,0.05)";
        editBtn.style.background = "#444";
    };
    item.onclick = () => {
        if (!reviewSelectedTs) return;

        let oldSong = "";
        const selectedRow = document.querySelector(`[data-result-row][data-row-ts="${reviewSelectedTs}"]`);
        if (selectedRow) {
            const songSpan = selectedRow.querySelector(".songContainer span[title]");
            if (songSpan) oldSong = songSpan.textContent.trim();
        }

        const capturedTs = reviewSelectedTs;
        const encodedTs = encodeURIComponent(capturedTs);
        const encodedSong = encodeURIComponent(song.display);
        const encodedOldSong = encodeURIComponent(oldSong);
        fetch(`http://127.0.0.1:5000/update_result?ts=${encodedTs}&song=${encodedSong}&old_song=${encodedOldSong}`)
        .then(r => r.json())
        .then(res => {
            if (res.replaced) {
                showToast(`${capturedTs} → ${song.display}`, "#2e7d32");
                // Try incremental update first (no flicker)
                const updated = updateSingleResultRow(capturedTs, song.display);
                if (!updated) {
                    // Fallback to full re-render if incremental update failed
                    reviewLastMtime = 0;
                    fetchResultsFile();
                }
                // Keep panels visible for further edits (don't hide)
            } else {
                showToast("Replace failed — timestamp not found", "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: update_result failed", e);
            showToast("Replace failed", "#c62828");
        });
    };
    return item;
}

/**
 * Add the song input section to the unified panel.
 * Creates form fields for adding new songs.
 * @returns {void}
 */
function addSongInputSection() {
    const container = document.getElementById("jrpd-unified-add-song-container");
    if (!container || container.querySelector(".jrpd-add-song-section")) return;
    
    const section = document.createElement("div");
    section.className = "jrpd-add-song-section";
    section.style.cssText = "display: flex; flex-direction: column; gap: 4px;";
    
    const title = document.createElement("div");
    title.textContent = "➕ Add New Song";
    title.style.cssText = "font-size: 11px; font-weight: bold; color: #aaa; margin-bottom: 4px;";
    section.appendChild(title);
    
    const fieldDefs = [
        {id: `jrpd-review-add-key`, placeholder: "Song Name (required)"},
        {id: `jrpd-review-add-intl`, placeholder: "Intl Name"},
        {id: `jrpd-review-add-artist`, placeholder: "Artist"},
        {id: `jrpd-review-add-artist-intl`, placeholder: "Intl Artist"},
    ];
    const inputStyle = "width: 100%; box-sizing: border-box; padding: 4px 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; font-size: 11px;";
    fieldDefs.forEach(def => {
        const input = document.createElement("input");
        input.id = def.id;
        input.placeholder = def.placeholder;
        input.style.cssText = inputStyle;
        section.appendChild(input);
    });
    
    const addBtn = document.createElement("button");
    addBtn.textContent = "Add & Replace";
    addBtn.style.cssText = "width: 100%; padding: 6px; background: #2e7d32; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: bold; margin-top: 2px;";
    addBtn.onclick = () => {
    	const keyInput = document.getElementById(`jrpd-review-add-key`);
    	const key = keyInput ? keyInput.value.trim() : "";
    	if (!key) {
    		showToast("Song Name is required", "#c62828");
    		return;
    	}
    	if (!reviewSelectedTs) {
    		showToast("Select a timestamp first", "#c62828");
    		return;
    	}
   
    	let oldSong = "";
    	const selectedRow = document.querySelector(`[data-result-row][data-row-ts="${reviewSelectedTs}"]`);
    	if (selectedRow) {
    		const songSpan = selectedRow.querySelector(".songContainer span[title]");
    		if (songSpan) {
    			oldSong = songSpan.textContent.trim();
    		}
    	}
   
    	const intlInput = document.getElementById(`jrpd-review-add-intl`);
    	const artistInput = document.getElementById(`jrpd-review-add-artist`);
    	const artistIntlInput = document.getElementById(`jrpd-review-add-artist-intl`);
   
    	const params = new URLSearchParams({
    		ts: reviewSelectedTs,
    		old_song: oldSong,
    		key: key,
    		intl: intlInput ? intlInput.value.trim() : "",
    		artist_orig: artistInput ? artistInput.value.trim() : "",
    		artist_intl: artistIntlInput ? artistIntlInput.value.trim() : ""
    	});
   
    	// Build the display string for the new song
    	const newSongDisplay = buildSongDisplay(key, intlInput?.value.trim(), artistInput?.value.trim(), artistIntlInput?.value.trim());
   
    	fetch(`http://127.0.0.1:5000/add_song_and_update?${params.toString()}`)
    	.then(r => r.json())
    	.then(res => {
    		if (res.status === "ok") {
    			showToast(`Added to songs.json: ${key}`, "#2e7d32");
                fieldDefs.forEach(def => {
                    const el = document.getElementById(def.id);
                    if (el) el.value = "";
                });
                // Try incremental update first (no flicker)
                const updated = updateSingleResultRow(reviewSelectedTs, newSongDisplay);
                if (!updated) {
                    // Fallback to full re-render if incremental update failed
                    reviewLastMtime = 0;
                    fetchResultsFile();
                }
                // Keep panels visible for further edits (don't hide)
            } else {
                showToast("Add failed: " + (res.msg || "unknown error"), "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: add_song_and_update failed", e);
            showToast("Add failed", "#c62828");
        });
    };
    section.appendChild(addBtn);
    container.appendChild(section);
}

/**
 * Show the edit song form modal.
 * @param {string} songKey - The song key to edit
 * @param {string} songDisplay - The display name
 * @param {string} [songIntl] - International name
 * @param {string} [songArtistOrig] - Original artist
 * @param {string} [songArtistIntl] - International artist
 * @returns {void}
 */
function showEditSongForm(songKey, songDisplay, songIntl, songArtistOrig, songArtistIntl) {
    // Create overlay modal for editing
    const overlay = document.createElement("div");
    overlay.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; display: flex; align-items: center; justify-content: center;";

    const modal = document.createElement("div");
    modal.style.cssText = "background: #2a2a3e; color: #eee; padding: 20px; border-radius: 10px; min-width: 400px; max-width: 600px; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.8);";

    const title = document.createElement("h3");
    title.textContent = `Edit Song: ${songKey}`;
    title.style.marginTop = "0";
    title.style.color = "#82b1ff";
    modal.appendChild(title);

    // Use raw values from song data (passed as parameters)
    let currentIntl = songIntl || "";
    let currentArtistOrig = songArtistOrig || "";
    let currentArtistIntl = songArtistIntl || "";
    
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
    intlInput.value = currentIntl;
    intlInput.placeholder = "Enter international name";
    intlInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(intlInput);
    
    // Original Artist
    const artistOrigLabel = document.createElement("label");
    artistOrigLabel.textContent = "Original Artist:";
    form.appendChild(artistOrigLabel);
    
    const artistOrigInput = document.createElement("input");
    artistOrigInput.type = "text";
    artistOrigInput.value = currentArtistOrig;
    artistOrigInput.placeholder = "Enter original artist";
    artistOrigInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 10px;";
    form.appendChild(artistOrigInput);
    
    // International Artist
    const artistIntlLabel = document.createElement("label");
    artistIntlLabel.textContent = "International Artist:";
    form.appendChild(artistIntlLabel);
    
    const artistIntlInput = document.createElement("input");
    artistIntlInput.type = "text";
    artistIntlInput.value = currentArtistIntl;
    artistIntlInput.placeholder = "Enter international artist";
    artistIntlInput.style.cssText = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; margin-bottom: 15px;";
    form.appendChild(artistIntlInput);
    
    // Buttons container
    const buttonsDiv = document.createElement("div");
    buttonsDiv.style.cssText = "display: flex; gap: 10px; justify-content: flex-end;";
    
    const saveBtn = document.createElement("button");
    saveBtn.type = "submit";
    saveBtn.textContent = "Save Changes";
    saveBtn.style.cssText = "padding: 8px 16px; background: #2e7d32; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;";
    
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = "padding: 8px 16px; background: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;";
    cancelBtn.onclick = () => {
        document.body.removeChild(overlay);
    };
    
    buttonsDiv.appendChild(cancelBtn);
    buttonsDiv.appendChild(saveBtn);
    form.appendChild(buttonsDiv);
    
    form.onsubmit = (e) => {
        e.preventDefault();
    
        // Prepare form data for POST request
        const params = new URLSearchParams();
        params.append('key', songKey);
        params.append('intl', intlInput.value.trim());
        params.append('artist_orig', artistOrigInput.value.trim());
        params.append('artist_intl', artistIntlInput.value.trim());
    
        // DEBUG: Log what's being sent
        console.log("JRPD: [DEBUG] Sending update_song_vars request");
        console.log("JRPD: [DEBUG] songKey:", songKey);
        console.log("JRPD: [DEBUG] intl:", intlInput.value.trim());
        console.log("JRPD: [DEBUG] artist_orig:", artistOrigInput.value.trim());
        console.log("JRPD: [DEBUG] artist_intl:", artistIntlInput.value.trim());
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
                // Close modal and refresh the song lists
                document.body.removeChild(overlay);
                // Refresh the song lists to show updated values
                if (songListsCache) {
                    // Capture current search value before refresh
                    const searchInput = document.getElementById("jrpd-unified-search");
                    const currentSearch = searchInput ? searchInput.value : "";
                    
                    // Clear cache to force refresh
                    songListsCache = null;
                    fetch("http://127.0.0.1:5000/song_lists")
                    .then(r => r.json())
                    .then(data => {
                        songListsCache = data;
                        // Re-apply search filter instead of clearing
                        if (currentSearch) {
                            filterSongPanel(currentSearch);
                        } else {
                            populateSongPanels(data);
                        }
                    })
                    .catch(e => console.error("JRPD: Failed to refresh song_lists", e));
                }
            } else {
                showToast("Update failed: " + (res.msg || "unknown error"), "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: update_song_vars failed", e);
            showToast("Update failed", "#c62828");
            document.body.removeChild(overlay);
        });
    };
    
    modal.appendChild(form);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}