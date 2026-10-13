// JRPD Results Review Panel
// Handles results display, editing, and playback controls

let reviewFontSize = 11;
const PREFS_KEY = "jrpd-review-prefs";

// ---- Server URL helpers (YouTube loopback vs Bilibili LAN) ----
function getReviewServerUrl() {
    if (typeof jrpdGetServerBase === "function") return jrpdGetServerBase();
    return window.location.hostname.includes("bilibili.com")
        ? ((typeof JRPD_BILIBILI_HOST !== "undefined") ? JRPD_BILIBILI_HOST : "http://192.168.100.108:5000")
        : ((typeof JRPD_LOCAL_HOST !== "undefined") ? JRPD_LOCAL_HOST : "http://127.0.0.1:5000");
}

/** Cross-platform fetch (uses GM_xmlhttpRequest on Bilibili when available). */
function reviewFetch(url, options) {
    const fetchFn = typeof jrpdFetch !== "undefined" ? jrpdFetch : fetch;
    return fetchFn(url, options);
}

// ---- Panel visibility (available during marking and review) ----
function isResultsPanelVisible() {
    const panel = document.getElementById("jrpd-results-panel");
    return !!panel && panel.style.display !== "none";
}

function openResultsPanel(persist = true) {
    const panel = document.getElementById("jrpd-results-panel");
    if (!panel) return;
    panel.style.display = "flex";
    if (persist) savePanelPrefs({ panelVisible: true });
    updatePanelToggleButton();
    fetchResultsFile();
}

function closeResultsPanel() {
    const panel = document.getElementById("jrpd-results-panel");
    if (panel) panel.style.display = "none";
    savePanelPrefs({ panelVisible: false });
    hideSongPanels();
    updatePanelToggleButton();
}

function toggleResultsPanel() {
    if (isResultsPanelVisible()) closeResultsPanel();
    else openResultsPanel();
}

function updatePanelToggleButton() {
    const btn = document.getElementById("jrpd-panel-toggle-btn");
    if (btn) btn.style.opacity = isResultsPanelVisible() ? "1" : "0.55";
}

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
        const response = await reviewFetch(getReviewServerUrl() + "/paren_exceptions");
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

function toggleFlagMark(ts) {
    const row = document.querySelector(`[data-result-row][data-row-ts="${ts}"]`);
    const flagBtn = row ? row.querySelector(".flagBtn") : null;
    const want = !(typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(ts));
    if (flagBtn) {
        flagBtn.disabled = true;
        flagBtn.textContent = "⏳";
        flagBtn.style.opacity = "1";
    }
    reviewFetch(getReviewServerUrl() + `/toggle_flag?ts=${encodeURIComponent(ts)}&flag=${want ? "1" : "0"}`)
    .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    })
    .then(res => {
        if (res.status === "ok") {
            const flagged = !!res.flagged;
            if (flagged) flaggedTimestamps.add(ts);
            else flaggedTimestamps.delete(ts);
            saveFlaggedTimestamps();
            updateFlagRowState(ts);
            showToast(flagged ? `${ts} flagged for manual fix` : `${ts} unflagged`, flagged ? "#f57f17" : "#2e7d32");
            reviewLastMtime = 0;
            fetchResultsFile({ forceFullRender: true });
        } else {
            if (flagBtn) flagBtn.disabled = false;
            updateFlagRowState(ts);
            showToast("Flag failed: " + (res.msg || "unknown error"), "#c62828");
        }
    })
    .catch(e => {
        console.error("JRPD: toggle_flag failed", e);
        if (flagBtn) flagBtn.disabled = false;
        updateFlagRowState(ts);
        showToast(`Flag failed for ${ts} — server may need restart`, "#c62828");
    });
}

/**
 * Clear the manual-review flag for a row that was just fixed
 * (song assigned, identified, or blanked). UI-only; the server
 * already dropped the file marker via the fix endpoint.
 * @param {string} ts - Timestamp of the fixed row
 */
function unflagRow(ts) {
    if (typeof flaggedTimestamps === "undefined") return;
    if (flaggedTimestamps.has(ts)) {
        flaggedTimestamps.delete(ts);
        saveFlaggedTimestamps();
        updateFlagRowState(ts);
    }
}

function updateFlagRowState(ts) {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return;
    const row = list.querySelector(`[data-row-ts="${ts}"]`);
    if (!row) return;
    const isFlagged = flaggedTimestamps.has(ts);
    const flagBtn = row.querySelector(".flagBtn");
    if (flagBtn) {
        flagBtn.textContent = isFlagged ? "🚩" : "🏳️";
        flagBtn.style.opacity = isFlagged ? "1" : "0.45";
        flagBtn.style.background = isFlagged ? "#ffeb3b" : "transparent";
        flagBtn.title = isFlagged ? "Unflag (done)" : "Flag for manual fix";
    }
    let badge = row.querySelector(".flagBadge");
    if (isFlagged && !badge) {
        badge = document.createElement("span");
        badge.className = "flagBadge";
        badge.textContent = "🚩 CHECK";
        badge.style.cssText = "background: #ffeb3b; color: #000; font-weight: bold; padding: 1px 6px; border-radius: 3px; font-size: 10px; flex-shrink: 0; margin-left: auto; white-space: nowrap;";
        row.appendChild(badge);
    } else if (!isFlagged && badge) {
        badge.remove();
    }
}

function loadFlaggedTimestamps() {
    try {
        const raw = localStorage.getItem(PREFS_KEY);
        if (raw) {
            const prefs = JSON.parse(raw);
            if (prefs.flaggedTimestamps && Array.isArray(prefs.flaggedTimestamps)) {
                flaggedTimestamps = new Set(prefs.flaggedTimestamps);
            }
        }
    } catch (e) {}
}

function saveFlaggedTimestamps() {
    try {
        const prefs = loadPanelPrefs();
        prefs.flaggedTimestamps = Array.from(flaggedTimestamps);
        // Drop legacy heart marks if present
        if (prefs.heartMarkedTimestamps) delete prefs.heartMarkedTimestamps;
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {
        console.error("JRPD: Failed to save flag marks:", e);
    }
}

/**
 * Clear a result row (leave it blank) via the server.
 * @param {string} ts - Timestamp of the row to blank
 */
function clearResultRow(ts) {
    let oldSong = "";
    const row = document.querySelector(`[data-result-row][data-row-ts="${ts}"]`);
    if (row) {
        const songSpan = row.querySelector(".songContainer span[title]");
        if (songSpan) oldSong = songSpan.title || songSpan.textContent.trim();
    }
    reviewFetch(getReviewServerUrl() + `/update_result?ts=${encodeURIComponent(ts)}&song=&old_song=${encodeURIComponent(oldSong)}`)
    .then(r => r.json())
    .then(res => {
        if (res.replaced) {
            unflagRow(ts);
            showToast(`${ts} cleared (blank)`, "#ff9800");
            reviewLastMtime = 0;
            fetchResultsFile({ forceFullRender: true });
        } else {
            showToast("Clear failed — timestamp not found", "#c62828");
        }
    })
    .catch(e => {
        console.error("JRPD: clear row failed", e);
        showToast("Clear failed", "#c62828");
    });
}

/**
 * Re-identify a result row with ACRCloud via the server.
 * Uses the server's local audio file; updates results.txt on a match.
 * @param {string} ts - Timestamp of the row to identify
 * @param {HTMLElement} [btn] - The button element (shows spinner while busy)
 */
function identifyRowWithAcr(ts, btn) {
    if (!ts) return;
    if (btn) {
        if (btn.dataset.busy === "1") return;
        btn.dataset.busy = "1";
        btn.dataset.origText = btn.textContent;
        btn.textContent = "⏳";
        btn.style.opacity = "1";
        btn.disabled = true;
    }
    showToast(`Identifying ${ts} with ACRCloud...`, "#1565c0");
    reviewFetch(getReviewServerUrl() + `/acr_identify?ts=${encodeURIComponent(ts)}`)
    .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    })
    .then(res => {
        console.log("JRPD: acr_identify response for", ts, res);
        if (res.status === "ok" && res.identified && res.song) {
            unflagRow(ts);
            // Manual identification: toast the row copy like the Marked toast
            jrpdNotifyIdentPopup(jrpdBuildIdentPopupText(ts, res.song), true);
            // Suppress the auto-detection duplicate (poll will see the same resolved value)
            try { if (jrpdPrevResultsMap) jrpdPrevResultsMap[ts] = res.song; } catch (e) {}
            if (res.detail) showAcrDetailModal(ts, res.detail, res.candidates, true);
            reviewLastMtime = 0;
            fetchResultsFile({ forceFullRender: true });
        } else if (res.status === "ok" && !res.identified) {
            if (res.detail) {
                const d = res.detail || {};
                const rawName = `${d.title || "?"} - ${d.artist || "?"}`;
                jrpdNotifyIdentPopup(`${ts} ${rawName} (no DB match)`, false);
                showAcrDetailModal(ts, res.detail, res.candidates, false);
            } else {
                jrpdNotifyIdentPopup(`${ts} (empty)`, false);
            }
        } else {
            showToast("ACR failed: " + (res.msg || "unknown error"), "#c62828");
        }
    })
    .catch(e => {
        console.error("JRPD: acr_identify failed", e);
        const msg = String((e && e.message) || e);
        if (msg.includes("404")) {
            showToast("ACR endpoint missing — restart python server", "#c62828");
        } else {
            showToast(`ACR identify failed for ${ts}`, "#c62828");
        }
    })
    .finally(() => {
        if (btn) {
            btn.dataset.busy = "";
            btn.textContent = btn.dataset.origText || "🔍";
            btn.style.opacity = "0.7";
            btn.disabled = false;
        }
    });
}

/**
 * Show a modal with full ACRCloud details for a row.
 * Lets the user copy title/artist/album/links for manual identification
 * even when there is no songs.json database match.
 * @param {string} ts - Timestamp of the row
 * @param {Object} detail - Flattened detail object from /acr_identify
 * @param {Array} [candidates] - Other ACRCloud candidates
 * @param {boolean} [matched] - Whether a DB match was found
 */
function showAcrDetailModal(ts, detail, candidates, matched) {
    try {
        document.querySelectorAll(".jrpd-acr-modal-overlay").forEach(el => el.remove());
        const d = detail || {};
        const overlay = document.createElement("div");
        overlay.className = "jrpd-acr-modal-overlay";
        overlay.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10001; display: flex; align-items: center; justify-content: center;";

        const modal = document.createElement("div");
        modal.style.cssText = "background: #1e1e30; color: #eee; padding: 18px 20px; border-radius: 10px; min-width: 380px; max-width: 560px; max-height: 82vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.8); font-size: 12px; line-height: 1.6;";

        const title = document.createElement("h3");
        title.style.cssText = "margin: 0 0 4px 0; color: #82b1ff; font-size: 14px;";
        title.textContent = `🔍 ACRCloud raw — ${ts}${matched ? " (matched)" : " (no DB match)"}`;
        modal.appendChild(title);

        const head = document.createElement("div");
        head.style.cssText = "font-size: 13px; font-weight: bold; color: #fff; margin-bottom: 8px;";
        head.textContent = `${d.title || "?"} - ${d.artist || "?"}`;
        modal.appendChild(head);

        if (d.en_title) {
            const en = document.createElement("div");
            en.style.cssText = "color: #aaa; margin-bottom: 8px;";
            en.textContent = `EN: ${d.en_title}`;
            modal.appendChild(en);
        }

        const rows = [
            ["Album", d.album],
            ["Release", d.release_date],
            ["Duration", d.duration_sec != null ? `${d.duration_sec}s` : null],
            ["Score", d.score],
            ["Label", d.label],
            ["Genres", (d.genres && d.genres.length) ? d.genres.join(", ") : null],
            ["ISRC", d.isrc],
            ["UPC", d.upc],
            ["Play offset", d.play_offset_ms != null ? `${d.play_offset_ms}ms` : null],
        ];
        const table = document.createElement("div");
        rows.forEach(([k, v]) => {
            if (v === null || v === undefined || v === "") return;
            const r = document.createElement("div");
            r.innerHTML = "";
            const kk = document.createElement("span");
            kk.style.cssText = "color: #888; display: inline-block; min-width: 90px;";
            kk.textContent = k + ": ";
            const vv = document.createElement("span");
            vv.style.cssText = "color: #eee; user-select: text;";
            vv.textContent = String(v);
            r.appendChild(kk);
            r.appendChild(vv);
            table.appendChild(r);
        });
        modal.appendChild(table);

        const linkRow = (label, url) => {
            if (!url) return;
            const div = document.createElement("div");
            const kk = document.createElement("span");
            kk.style.cssText = "color: #888; display: inline-block; min-width: 90px;";
            kk.textContent = label + ": ";
            const a = document.createElement("a");
            a.href = url;
            a.target = "_blank";
            a.rel = "noopener";
            a.style.cssText = "color: #82b1ff; word-break: break-all;";
            a.textContent = url;
            div.appendChild(kk);
            div.appendChild(a);
            modal.appendChild(div);
        };
        linkRow("Spotify", d.spotify_url);
        linkRow("Deezer", d.deezer_url);
        linkRow("YouTube", d.youtube_url);

        if (candidates && candidates.length > 1) {
            const cHead = document.createElement("div");
            cHead.style.cssText = "margin-top: 10px; color: #ffb74d; font-weight: bold;";
            cHead.textContent = `Other candidates (${candidates.length - 1}):`;
            modal.appendChild(cHead);
            candidates.slice(1, 5).forEach(c => {
                const cDiv = document.createElement("div");
                cDiv.style.cssText = "color: #ccc; margin-left: 8px;";
                cDiv.textContent = `• ${c.title || "?"} - ${c.artist || "?"} (score=${c.score}, album=${c.album || "-"})`;
                modal.appendChild(cDiv);
            });
        }

        const btnBar = document.createElement("div");
        btnBar.style.cssText = "display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px;";

        const copyBtn = document.createElement("button");
        copyBtn.textContent = "📋 Copy";
        copyBtn.style.cssText = "padding: 6px 14px; background: #0f3460; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;";
        copyBtn.onclick = () => {
            const lines = [
                `Title: ${d.title || ""}`,
                `Artist: ${d.artist || ""}`,
                d.en_title ? `EN: ${d.en_title}` : null,
                d.album ? `Album: ${d.album}` : null,
                d.release_date ? `Release: ${d.release_date}` : null,
                d.score != null ? `Score: ${d.score}` : null,
                d.label ? `Label: ${d.label}` : null,
                d.isrc ? `ISRC: ${d.isrc}` : null,
                d.spotify_url ? `Spotify: ${d.spotify_url}` : null,
                d.deezer_url ? `Deezer: ${d.deezer_url}` : null,
                d.youtube_url ? `YouTube: ${d.youtube_url}` : null,
            ].filter(Boolean).join("\n");
            try {
                navigator.clipboard.writeText(lines).then(() => showToast("ACR details copied", "#2e7d32"));
            } catch (e) {
                console.warn("JRPD: copy failed", e);
            }
        };
        btnBar.appendChild(copyBtn);

        const closeBtn = document.createElement("button");
        closeBtn.textContent = "Close";
        closeBtn.style.cssText = "padding: 6px 14px; background: #555; color: white; border: none; border-radius: 4px; cursor: pointer;";
        closeBtn.onclick = () => overlay.remove();
        btnBar.appendChild(closeBtn);

        modal.appendChild(btnBar);
        overlay.appendChild(modal);
        overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) overlay.remove(); });
        (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(overlay);
    } catch (e) {
        console.error("JRPD: showAcrDetailModal failed", e);
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

/**
 * Collect the current panel content as text lines ("ts song" per row).
 * Shared by the full-copy and chunked-copy buttons.
 * @returns {string[]} Lines in results.txt format
 */
function getResultsPanelLines() {
    const lines = [];
    const list = document.getElementById("jrpd-results-list");
    if (!list) return lines;
    list.querySelectorAll("[data-result-row]").forEach(row => {
        const tsSpan = row.querySelector("span.tsSpan");
        if (!tsSpan) return;
        const ts = (tsSpan.textContent || "").trim().replace(/\s+/g, " ");
        if (!ts) return;
        let content = "";

        const gapLabel = row.querySelector(".gapLabel");
        if (!gapLabel) {
            const songContainer = row.querySelector(".songContainer");
            if (songContainer) {
                const songSpan = songContainer.querySelector("span[title]");
                if (songSpan) {
                    const raw = (songSpan.title || songSpan.textContent || "").trim();
                    // Flatten any embedded newlines so one row always equals one line
                    content = (raw === "Processing..." ? "Processing..." : (songSpan.textContent || "").trim()).replace(/\r\n?/g, "\n").replace(/\n+/g, " ").replace(/\s+/g, " ").trim();
                } else {
                    const spans = songContainer.querySelectorAll("span");
                    for (const span of spans) {
                        if (!(span.textContent || "").includes('✏️')) {
                            content = (span.textContent || "").trim().replace(/\r\n?/g, "\n").replace(/\n+/g, " ").replace(/\s+/g, " ").trim();
                            break;
                        }
                    }
                }
            }
        }

        const rowTs = row.getAttribute("data-row-ts");
        const isFlagged = typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(rowTs);
        // Suffix format matches results.txt so pasted lines re-parse correctly
        const flagSuffix = isFlagged ? " 🚩" : "";

        if (content && content !== "Processing...") {
            lines.push(`${ts} ${content}${flagSuffix}`.trim());
        } else {
            lines.push(`${ts}${flagSuffix}`.trim());
        }
    });
    // Drop any accidental blanks so join("\n") never yields "\n\n"
    return lines.map(l => String(l || "").replace(/\r\n?/g, "\n").trim()).filter(l => l.length > 0);
}

/**
 * Split lines into chunks where each chunk is strictly less than maxChars.
 * Lines are never broken mid-text; a single over-long line becomes its own chunk.
 * @param {string[]} lines
 * @param {number} maxChars
 * @returns {string[]}
 */
function splitLinesIntoChunks(lines, maxChars = 1000) {
    const clean = (Array.isArray(lines) ? lines : [])
        .map(l => String(l == null ? "" : l).replace(/\r\n?/g, "\n").trim())
        .filter(l => l.length > 0)
        .map(l => l.replace(/\n+/g, " "));
    const chunks = [];
    let current = "";
    for (const line of clean) {
        const candidate = current ? current + "\n" + line : line;
        if (candidate.length < maxChars) {
            current = candidate;
        } else {
            if (current) chunks.push(current);
            if (line.length < maxChars) {
                current = line;
            } else {
                // Over-long single line: keep whole on its own chunk
                chunks.push(line);
                current = "";
            }
        }
    }
    if (current) chunks.push(current);
    return chunks;
}

function jrpdSleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function createResultsPanel() {
    if (document.getElementById("jrpd-results-panel")) return;

    const prefs = loadPanelPrefs();
    const savedFontSize = parseInt(prefs.fontSize, 10);
    if (!isNaN(savedFontSize)) reviewFontSize = savedFontSize;
    loadFlaggedTimestamps();

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
    title.textContent = "📋 Live Results & Review";
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
        opt.value = String(sz);
        opt.textContent = sz + "px";
        if (sz === reviewFontSize) opt.selected = true;
        fontSelect.appendChild(opt);
    });
    fontSelect.onchange = () => {
        reviewFontSize = parseInt(fontSelect.value, 10);
        const list = document.getElementById("jrpd-results-list");
        if (list) {
            list.style.fontSize = reviewFontSize + "px";
            // Rows carry their own inline font-size (set at creation time),
            // so the container change alone has no visible effect.
            // Propagate to all existing rows.
            list.querySelectorAll("[data-result-row]").forEach(row => {
                row.style.fontSize = reviewFontSize + "px";
            });
        }
        savePanelPrefs({ fontSize: reviewFontSize });
    };
    controlsGroup.appendChild(fontSelect);
    
    const copyBtn = document.createElement("button");
    copyBtn.textContent = "📋";
    copyBtn.title = "Copy results to clipboard";
    copyBtn.style.cssText = "padding: 2px 6px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; cursor: pointer; font-size: 13px;";
    copyBtn.onclick = () => {
        const lines = getResultsPanelLines();
        if (!lines.length) return;

        const textToCopy = lines.join("\n").replace(/\r\n?/g, "\n").replace(/\n{2,}/g, "\n");
        navigator.clipboard.writeText(textToCopy).then(() => {
            showToast("Results copied to clipboard!", "#4caf50");
            if (isReviewMode) {
                isReviewMode = false;
                closeResultsPanel();
                reviewFetch(getReviewServerUrl() + "/close_review").catch(() => {});
            }
        }).catch(err => {
            console.error("JRPD: Failed to copy text: ", err);
            showToast("Failed to copy results", "#f44336");
        });
    };
    controlsGroup.appendChild(copyBtn);

    const chunkCopyBtn = document.createElement("button");
    chunkCopyBtn.textContent = "📑";
    chunkCopyBtn.title = "Copy results in parts (<1000 chars each)";
    chunkCopyBtn.style.cssText = "padding: 2px 6px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; cursor: pointer; font-size: 13px;";
    chunkCopyBtn.onclick = async () => {
        const lines = getResultsPanelLines();
        if (!lines.length) {
            showToast("Nothing to copy", "#ff9800");
            return;
        }
        const chunks = splitLinesIntoChunks(lines, 1000);
        if (!chunks.length) {
            showToast("Nothing to copy", "#ff9800");
            return;
        }
        const delayMs = 1200;
        chunkCopyBtn.disabled = true;
        const origText = chunkCopyBtn.textContent;
        try {
            for (let i = 0; i < chunks.length; i++) {
                chunkCopyBtn.textContent = `${i + 1}/${chunks.length}`;
                const chunkText = String(chunks[i] || "").replace(/\r\n?/g, "\n").replace(/\n{2,}/g, "\n");
                await navigator.clipboard.writeText(chunkText);
                if (i < chunks.length - 1) {
                    showToast(`Copied part ${i + 1}/${chunks.length} (${chunks[i].length} chars)...`, "#1565c0");
                    await jrpdSleep(delayMs);
                }
            }
            showToast(`Copied ${chunks.length} part${chunks.length > 1 ? "s" : ""}! Last part (${chunks[chunks.length - 1].length} chars) in clipboard`, "#4caf50");
        } catch (err) {
            console.error("JRPD: Failed to copy chunk: ", err);
            showToast("Failed to copy parts", "#f44336");
        } finally {
            chunkCopyBtn.disabled = false;
            chunkCopyBtn.textContent = origText;
        }
    };
    controlsGroup.appendChild(chunkCopyBtn);
    
    const reloadBtn = document.createElement("button");
    reloadBtn.textContent = "↻";
    reloadBtn.title = "Reload results.txt";
    reloadBtn.style.cssText = "padding: 2px 6px; background: #0f3460; color: #eee; border: 1px solid #444; border-radius: 3px; cursor: pointer; font-size: 13px;";
    reloadBtn.onclick = () => { reviewLastMtime = 0; lastRenderedLinesJson = ""; fetchResultsFile({ forceFullRender: true }); };
    controlsGroup.appendChild(reloadBtn);

    const doneBtn = document.createElement("button");
    doneBtn.textContent = "Done";
    doneBtn.title = "Save panel position and hide";
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
        const wasReview = isReviewMode;
        isReviewMode = false;
        closeResultsPanel();
        if (wasReview) {
            reviewFetch(getReviewServerUrl() + "/review_done").catch(() => {});
        } else {
            showToast("Panel state saved", "#2e7d32");
        }
    };
    controlsGroup.appendChild(doneBtn);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.title = "Hide panel (reopen anytime with 📋)";
    closeBtn.style.cssText = "padding: 2px 6px; background: #333; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 11px;";
    closeBtn.onclick = () => closeResultsPanel();
    controlsGroup.appendChild(closeBtn);

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

    // Make panel available during marking by default (unless explicitly closed)
    const isVisibleByDefault = prefs.panelVisible !== false;
    panel.style.display = isVisibleByDefault ? "flex" : "none";

    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(panel);
    updatePanelToggleButton();

    if (isVisibleByDefault) {
        setTimeout(() => fetchResultsFile(), 100);
    }
}

function parseResultsLine(line) {
    const match = line.match(/^(\d+:\d{2}(?::\d{2})?)\s?(.*)/);
    if (!match) return null;
    let song = (match[2] || "").trim();
    let flagged = false;
    // Strip trailing 🚩 manual-review marker (written by /toggle_flag)
    if (/\s*🚩\s*$/.test(song)) {
        flagged = true;
        song = song.replace(/\s*🚩\s*$/, "").trim();
    }
    return { ts: match[1], song: song, flagged: flagged };
}

/**
 * Rebuild the local flag set from parsed result lines (file is source of truth).
 * This picks up markers added/removed by hand in results.txt on reload.
 * @param {Array} parsed - Parsed entries with ts/flagged fields
 */
function syncFlagsFromParsed(parsed) {
    if (typeof flaggedTimestamps === "undefined") return;
    flaggedTimestamps = new Set(parsed.filter(e => e.flagged).map(e => e.ts));
    saveFlaggedTimestamps();
}

let lastRenderedLinesJson = "";

/**
 * Build the popup/row text for an identification result.
 * Success: "ts song". Fail (empty gap): "ts (empty)".
 * @param {string} ts - Timestamp (e.g. "1:30")
 * @param {string} song - Resolved song text ("" for fail)
 * @returns {string} Row content copy
 */
function jrpdBuildIdentPopupText(ts, song) {
    const s = (song || "").trim();
    if (!s || s === "Processing...") return `${ts} (empty)`;
    return `${ts} ${s}`;
}

/**
 * Reset identification detection snapshot (call on video change).
 * Next fetch only snapshots, never pops up for pre-existing rows.
 * @returns {void}
 */
function jrpdResetIdentDetection() {
    try {
        jrpdPrevResultsMap = null;
    } catch (e) {}
}

/**
 * Show an identification result exactly like the "time Marked" toast:
 * pops up with a copy of the row content, then disappears on its own.
 * @param {string} text - Row content copy
 * @param {boolean} ok - True for success (green), false for fail (orange)
 * @returns {void}
 */
function jrpdNotifyIdentPopup(text, ok) {
    try {
        const msg = String(text || "").trim();
        // The popup must never show the intermediate pending state: a
        // still-pending row resolves later and toasts on its own transition.
        if (!msg || /processing\.\.\./i.test(msg)) return;
        if (typeof showToast === "function") showToast(msg, ok ? "#2e7d32" : "#ff9800");
    } catch (e) {}
}

/**
 * Detect automatic identifications from a fresh /results_file payload.
 * Fires once per row when it transitions Processing... -> resolved song (success)
 * or Processing... -> empty gap (fail). First poll only snapshots.
 * @param {string[]} lines - Raw results.txt lines
 * @returns {void}
 */
function jrpdDetectIdentifications(lines) {
    try {
        const parsed = (lines || []).map(l => parseResultsLine(l)).filter(Boolean);
        const newMap = {};
        parsed.forEach(e => { newMap[e.ts] = e.song || ""; });
        if (typeof jrpdPrevResultsMap === "undefined" || jrpdPrevResultsMap === null) {
            jrpdPrevResultsMap = newMap;
            return;
        }
        const prevMap = jrpdPrevResultsMap;
        jrpdPrevResultsMap = newMap;
        Object.keys(newMap).forEach(ts => {
            const prev = prevMap[ts];
            const cur = newMap[ts];
            // Brand-new ts that arrived already resolved (e.g. after reload): skip, not a fresh identification.
            if (prev === "Processing..." && cur !== "Processing...") {
                jrpdNotifyIdentPopup(jrpdBuildIdentPopupText(ts, cur), !!cur);
            }
        });
    } catch (e) {
        console.warn("JRPD: ident detection failed", e);
    }
}

/**
 * Update song text and edit-button routing for an existing row.
 * Used by both the incremental in-place path and updateSingleResultRow so the
 * edit button always reflects the resolved row text, not a stale arg.
 * @param {HTMLElement} row
 * @param {string} resolvedSong - The canonical resolved song text for this row.
 * @returns {boolean} False if the row structure needs a full rebuild.
 */
function updateSongInRow(row, resolvedSong) {
    const isGap = !resolvedSong;
    const songContainer = row.querySelector(".songContainer");
    if (!songContainer) return true;
    const songSpan = songContainer.querySelector("span[title]");
    if (!songSpan) return true;
    if (isGap) {
        // Row turned into a gap: structure must be rebuilt.
        return false;
    }
    if (resolvedSong === "Processing...") {
        songSpan.textContent = "⏳ Identifying...";
        songSpan.title = "Processing...";
        songSpan.style.color = "#ffb74d";
        songSpan.style.fontStyle = "italic";
        row.style.background = "#232015";
        row.style.borderLeft = "3px solid #ffb74d";
    } else {
        songSpan.textContent = resolvedSong;
        songSpan.title = resolvedSong;
        songSpan.style.color = "#ccc";
        songSpan.style.fontStyle = "normal";
        row.style.background = "#1e1e30";
        row.style.borderLeft = "none";
    }
    const editBtn = songContainer.querySelector("button");
    if (editBtn) {
        const ts = row.getAttribute("data-row-ts");
        const effectiveSong = songSpan.title || songSpan.textContent.trim();
        const isEffectiveProcessing = effectiveSong === "Processing..." || effectiveSong === "⏳ Identifying...";
        const newEditBtn = editBtn.cloneNode(true);
        newEditBtn.title = isEffectiveProcessing ? "Assign song from database" : "Edit song variables";
        newEditBtn.onclick = (e) => {
            e.stopPropagation();
            if (isEffectiveProcessing) {
                reviewSelectedTs = ts;
                showSongPanels(ts);
            } else {
                showEditSongFormForRow(ts, effectiveSong);
            }
        };
        editBtn.parentNode.replaceChild(newEditBtn, editBtn);
    }
    return true;
}

function fetchResultsFile(options = {}) {
    const { forceFullRender = false, preserveScroll = true } = options;
    reviewFetch(getReviewServerUrl() + "/results_file")
    .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    })
    .then(data => {
        const lines = data.lines || [];
        const linesJson = JSON.stringify(lines);
        if (!forceFullRender && data.mtime && data.mtime === reviewLastMtime && linesJson === lastRenderedLinesJson) {
            return;
        }
        reviewLastMtime = data.mtime || 0;
        lastRenderedLinesJson = linesJson;
        console.log("JRPD: results updated:", lines.length, "lines");
        jrpdDetectIdentifications(lines);
        renderResultsPanel(lines, { forceFullRender, preserveScroll });
    })
    .catch(e => {
        // Server may be starting up or not yet running
        const list = document.getElementById("jrpd-results-list");
        if (list && list.querySelectorAll("[data-result-row]").length === 0) {
            if (!list.querySelector(".jrpd-offline-msg")) {
                list.textContent = "";
                const msg = document.createElement("div");
                msg.className = "jrpd-offline-msg";
                msg.style.cssText = "color: #ffb74d; font-style: italic; text-align: center; padding: 24px 10px; font-size: 11px; line-height: 1.5;";
                msg.textContent = "⏳ Waiting for server connection (port 5000)... Start python label_marks_complete.py to begin.";
                list.appendChild(msg);
            }
        }
    });
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
    
    if (wasGap !== isNowGap) {
        return false; // gap status changed: rebuild the row structure
    }
    if (isNowGap) {
        return true;
    }
    return updateSongInRow(row, newSong);
}

/**
 * Add a mark optimistically to the live results panel.
 * @param {string} ts - Formatted timestamp (e.g. "1:30")
 * @param {string} [status="Processing..."] - Song text / status
 */
function addOptimisticResultRow(ts, status = "Processing...") {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return;

    // Remove empty message if present
    const emptyMsg = list.querySelector(".jrpd-empty-msg");
    if (emptyMsg) emptyMsg.remove();

    // Check if timestamp already exists
    const existing = list.querySelector(`[data-row-ts="${ts}"]`);
    if (existing) return;

    const existingRows = Array.from(list.querySelectorAll("[data-result-row]"));
    const entries = existingRows.map(r => {
        const rTs = r.getAttribute("data-row-ts");
        const songSpan = r.querySelector(".songContainer span[title]");
        const isGap = r.querySelector(".gapLabel") !== null;
        const isFlagged = r.querySelector(".flagBadge") !== null;
        return { ts: rTs, song: isGap ? "" : (songSpan ? (songSpan.title || songSpan.textContent.trim()) : ""), flagged: isFlagged };
    });

    entries.push({ ts: ts, song: status, flagged: false });
    entries.sort((a, b) => {
        const tA = typeof parseTimestampToSeconds === "function" ? parseTimestampToSeconds(a.ts) : 0;
        const tB = typeof parseTimestampToSeconds === "function" ? parseTimestampToSeconds(b.ts) : 0;
        return tA - tB;
    });

    list.textContent = "";
    entries.forEach((entry, idx) => {
        const row = createResultRow(entry, idx, entries);
        list.appendChild(row);
    });

    // Auto-scroll to newly added row
    const newRow = list.querySelector(`[data-row-ts="${ts}"]`);
    if (newRow) {
        newRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

/**
 * Remove a mark optimistically from the live results panel (for UNDO).
 * @param {string} ts - Formatted timestamp
 */
function removeOptimisticResultRow(ts) {
    const list = document.getElementById("jrpd-results-list");
    if (!list) return;
    const row = list.querySelector(`[data-row-ts="${ts}"]`);
    if (row) {
        row.remove();
    }
    const remaining = list.querySelectorAll("[data-result-row]");
    if (remaining.length === 0) {
        renderResultsPanel([]);
    }
}

// Make accessible globally
if (typeof window !== "undefined") {
    window.addOptimisticResultRow = addOptimisticResultRow;
    window.removeOptimisticResultRow = removeOptimisticResultRow;
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
    const isProcessing = entry.song === "Processing...";
    const row = document.createElement("div");
    row.setAttribute("data-result-row", "1");
    row.setAttribute("data-row-ts", entry.ts);
    let rowBg = "background: #1e1e30;";
    if (isGap) {
        rowBg = "background: #2a1a1a; border-left: 3px solid #ff5252;";
    } else if (isProcessing) {
        rowBg = "background: #232015; border-left: 3px solid #ffb74d;";
    }
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

    // Play button (seek only — does NOT open the song panel)
    const seekBtn = document.createElement("button");
    seekBtn.textContent = "▶";
    seekBtn.title = `Seek & loop ${entry.ts}`;
    const isActive = reviewActiveGapTs === entry.ts;
    const btnColor = isGap ? "#c62828" : (isProcessing ? "#6d4c00" : "#0f3460");
    const btnActiveColor = isGap ? "#ff5252" : (isProcessing ? "#ffa000" : "#1a73e8");
    seekBtn.style.cssText = `padding: 1px 6px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; ${isActive ? `background: ${btnActiveColor}; color: white;` : `background: ${btnColor}; color: #ccc;`}`;
    seekBtn.setAttribute("data-gap-ts", entry.ts);
    seekBtn.onclick = (e) => {
        e.stopPropagation();
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

    // Add-song button (opens the song panel for this row)
    const addSongBtn = document.createElement("button");
    addSongBtn.textContent = "➕";
    addSongBtn.title = `Add/select song for ${entry.ts}`;
    addSongBtn.className = "addSongBtn";
    addSongBtn.style.cssText = "padding: 1px 5px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: #2e7d32; color: white;";
    addSongBtn.onclick = (e) => {
        e.stopPropagation();
        const list = document.getElementById("jrpd-results-list");
        if (list) list.querySelectorAll("[data-result-row]").forEach(r => { r.style.outline = "none"; });
        row.style.outline = "2px solid #ffeb3b";
        row.style.outlineOffset = "-1px";
        showSongPanels(entry.ts);
    };
    row.appendChild(addSongBtn);

    // Flag button (mark row for manual fix in results.txt)
    const isFlagged = !!entry.flagged || (typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(entry.ts));
    const flagBtn = document.createElement("button");
    flagBtn.textContent = isFlagged ? "🚩" : "🏳️";
    flagBtn.title = isFlagged ? "Unflag (done)" : "Flag for manual fix";
    flagBtn.className = "flagBtn";
    flagBtn.style.cssText = `padding: 1px 4px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: ${isFlagged ? "#ffeb3b" : "transparent"}; opacity: ${isFlagged ? "1" : "0.45"};`;
    flagBtn.onclick = (e) => {
        e.stopPropagation();
        toggleFlagMark(entry.ts);
    };
    row.appendChild(flagBtn);

    // Clear button (leave row blank / delete current content)
    const clearBtn = document.createElement("button");
    clearBtn.textContent = "🧹";
    clearBtn.title = `Clear song (leave ${entry.ts} blank)`;
    clearBtn.className = "clearBtn";
    clearBtn.style.cssText = "padding: 1px 4px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: transparent; opacity: 0.7;";
    clearBtn.onclick = (e) => {
        e.stopPropagation();
        clearResultRow(entry.ts);
    };
    row.appendChild(clearBtn);

    // ACRCloud identify button (re-identify this row via server audio)
    const acrBtn = document.createElement("button");
    acrBtn.textContent = "🔍";
    acrBtn.title = `Identify with ACRCloud (${entry.ts})`;
    acrBtn.className = "acrBtn";
    acrBtn.style.cssText = "padding: 1px 4px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: transparent; opacity: 0.7;";
    acrBtn.onclick = (e) => {
        e.stopPropagation();
        identifyRowWithAcr(entry.ts, acrBtn);
    };
    row.appendChild(acrBtn);

    const tsSpan = document.createElement("span");
    tsSpan.className = "tsSpan";
    tsSpan.textContent = entry.ts;
    const tsColor = isGap ? "#ff8a80" : (isProcessing ? "#ffb74d" : "#82b1ff");
    tsSpan.style.cssText = `font-family: monospace; flex-shrink: 0; min-width: 42px; font-size: inherit; color: ${tsColor}; ${isGap ? "font-weight: bold;" : ""}`;
    row.appendChild(tsSpan);

    if (isGap) {
        const gapLabel = document.createElement("span");
        gapLabel.className = "gapLabel";
        gapLabel.textContent = "(empty)";
        gapLabel.style.cssText = "color: #666; font-style: italic; font-size: inherit;";
        row.appendChild(gapLabel);
    } else {
        // Create container for song info and edit button
        const songContainer = document.createElement("div");
        songContainer.className = "songContainer";
        songContainer.style.cssText = "display: flex; align-items: flex-start; gap: 5px; flex-grow: 1;";

        const songSpan = document.createElement("span");
        if (isProcessing) {
            songSpan.textContent = "⏳ Identifying...";
            songSpan.style.cssText = "color: #ffb74d; font-style: italic; word-break: break-word; white-space: normal; font-size: inherit; flex-grow: 1;";
            songSpan.title = "Processing...";
        } else {
            songSpan.textContent = entry.song;
            songSpan.style.cssText = "color: #ccc; word-break: break-word; white-space: normal; font-size: inherit; flex-grow: 1;";
            songSpan.title = entry.song;
        }
        songContainer.appendChild(songSpan);

        // Add edit button for existing songs or processing items
        const editBtn = document.createElement("button");
        editBtn.textContent = "✏️";
        editBtn.title = isProcessing ? "Assign song from database" : "Edit song variables";
        editBtn.style.cssText = "padding: 2px 4px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 10px; flex-shrink: 0;";
        editBtn.onclick = (e) => {
            e.stopPropagation();
            if (isProcessing) {
                reviewSelectedTs = entry.ts;
                showSongPanels(entry.ts);
            } else {
                showEditSongFormForRow(entry.ts, entry.song);
            }
        };
        songContainer.appendChild(editBtn);

        row.appendChild(songContainer);
    }

    // Flag badge at the end of the row (mirrors the 🚩 marker in results.txt)
    if (!!entry.flagged || (typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(entry.ts))) {
        const badge = document.createElement("span");
        badge.className = "flagBadge";
        badge.textContent = "🚩 CHECK";
        badge.style.cssText = "background: #ffeb3b; color: #000; font-weight: bold; padding: 1px 6px; border-radius: 3px; font-size: 10px; flex-shrink: 0; margin-left: auto; white-space: nowrap;";
        row.appendChild(badge);
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
    
    console.log("JRPD: [DEBUG] renderResultsPanel called with", lines.length, "lines");
    
    const parsed = lines.map(l => parseResultsLine(l)).filter(Boolean);

    // File is the source of truth for flags (also picks up hand edits in results.txt)
    syncFlagsFromParsed(parsed);
    
    // Save scroll position before any modifications
    const savedScrollTop = list.scrollTop;
    const wasAtBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
    
    // Empty state
    if (parsed.length === 0) {
        list.textContent = "";
        const emptyMsg = document.createElement("div");
        emptyMsg.className = "jrpd-empty-msg";
        emptyMsg.textContent = "No marks yet. Press 'A' to mark songs.";
        emptyMsg.style.cssText = "color: #777; font-style: italic; text-align: center; padding: 24px 10px; font-size: 12px;";
        list.appendChild(emptyMsg);
        return;
    }
    
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
                        if (songSpan && songSpan.title !== entry.song) {
                            if (!updateSongInRow(row, entry.song)) {
                                needsFullRebuild = true;
                            }
                        }
                    }

                    // Sync flag badge/button with the file marker (covers hand edits)
                    const hasBadge = row.querySelector(".flagBadge") !== null;
                    if (hasBadge !== !!entry.flagged) {
                        updateFlagRowState(entry.ts);
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

    // Restore scroll position after rebuild (pin to bottom if we were already there)
    if (preserveScroll) {
        list.scrollTop = wasAtBottom ? list.scrollHeight : savedScrollTop;
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
    overlay.className = "jrpd-modal-overlay";
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
        overlay.remove();
    };
    buttonsDiv.appendChild(cancelBtn);
    modal.appendChild(buttonsDiv);

    overlay.appendChild(modal);
    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(overlay);

    // Fetch existing song data from server
    let songData = {};
    try {
        const response = await reviewFetch(`${getReviewServerUrl()}/get_song_data?key=${encodeURIComponent(songKey)}`);
        if (response.ok) {
            songData = await response.json();
        } else {
            console.warn(`Failed to fetch song data: ${response.status}`);
        }
    } catch (e) {
        console.error("Error fetching song data:", e);
    }

    // Remove loading message
    overlay.remove();

    // Now build the actual form with fetched data
    const overlay2 = document.createElement("div");
    overlay2.className = "jrpd-modal-overlay";
    overlay2.style.cssText = overlay.style.cssText;
    const modal2 = document.createElement("div");
    modal2.style.cssText = modal.style.cssText;
    const title2 = document.createElement("h3");
    title2.textContent = `Edit Song: ${songKey}`;
    title2.style.marginTop = "0";
    title2.style.color = "#82b1ff";
    modal2.appendChild(title2);

    // Create form elements (all possible song fields; empty ones auto-collapsed)
    const form = document.createElement("form");
    form.style.cssText = "display: flex; flex-direction: column; gap: 10px;";

    // Song Key (readonly, always visible)
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

    const textDefs = [
        {key: "intl", label: "International Name:", placeholder: "Enter international name", title: ""},
        {key: "artist_orig", label: "Original Artist:", placeholder: "Enter original artist", title: ""},
        {key: "artist_intl", label: "International Artist:", placeholder: "Enter international artist", title: ""},
        {key: "info", label: "Info:", placeholder: "Enter extra info (version, etc.)", title: ""},
        {key: "remap", label: "Remap to (optional):", placeholder: "Enter target song name for remapping", title: "If set, this song name will be automatically remapped to the specified target on next identification"},
    ];
    const boolDefs = [
        {key: "discard", label: "Discard (skip in identification)", title: "If checked, this song is ignored during identification"},
        {key: "see_artist", label: "Require artist match (see_artist)", title: "If checked, title only matches when artist also matches"},
        {key: "intl_override", label: "Force stored intl (intl_override)", title: "If checked, use stored intl without Shazam EN fallback"},
    ];
    const fieldInputs = {};
    const emptyWrappers = [];
    const inputStyle = "padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; width: 100%; box-sizing: border-box;";

    textDefs.forEach(def => {
        const wrap = document.createElement("div");
        wrap.style.cssText = "display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px;";
        const lab = document.createElement("label");
        lab.textContent = def.label;
        wrap.appendChild(lab);
        const inp = document.createElement("input");
        inp.type = "text";
        inp.value = songData[def.key] || "";
        inp.placeholder = def.placeholder;
        if (def.title) inp.title = def.title;
        inp.style.cssText = inputStyle;
        wrap.appendChild(inp);
        fieldInputs[def.key] = inp;
        if ((songData[def.key] || "").toString().trim()) form.appendChild(wrap);
        else emptyWrappers.push(wrap);
    });

    boolDefs.forEach(def => {
        const wrap = document.createElement("div");
        wrap.style.cssText = "display: flex; align-items: center; gap: 8px; margin-bottom: 10px;";
        const inp = document.createElement("input");
        inp.type = "checkbox";
        inp.checked = !!songData[def.key];
        inp.style.cssText = "width: 16px; height: 16px; cursor: pointer;";
        if (def.title) inp.title = def.title;
        const lab = document.createElement("label");
        lab.textContent = def.label;
        if (def.title) lab.title = def.title;
        lab.style.cssText = "cursor: pointer; user-select: none;";
        lab.onclick = () => { inp.checked = !inp.checked; };
        wrap.appendChild(inp);
        wrap.appendChild(lab);
        fieldInputs[def.key] = inp;
        if (songData[def.key]) form.appendChild(wrap);
        else emptyWrappers.push(wrap);
    });

    if (emptyWrappers.length) {
        const details = document.createElement("details");
        details.style.cssText = "margin-bottom: 10px; border: 1px solid #444; border-radius: 4px; padding: 6px 8px;";
        const summary = document.createElement("summary");
        summary.textContent = `Show ${emptyWrappers.length} empty fields`;
        summary.style.cssText = "cursor: pointer; color: #aaa; font-size: 12px; user-select: none;";
        details.appendChild(summary);
        emptyWrappers.forEach(w => { w.style.marginBottom = "8px"; w.style.marginTop = "8px"; details.appendChild(w); });
        form.appendChild(details);
    }
    
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
        overlay2.remove();
    };
    
    buttonsDiv2.appendChild(cancelBtn2);
    buttonsDiv2.appendChild(saveBtn);
    form.appendChild(buttonsDiv2);
    
    form.onsubmit = (e) => {
        e.preventDefault();
    
        // Prepare form data for POST request (all fields; empty text = delete, unchecked = false/remove)
        const params = new URLSearchParams();
        params.append('key', songKey);
        ["intl", "artist_orig", "artist_intl", "info", "remap"].forEach(k => {
            params.append(k, (fieldInputs[k] ? fieldInputs[k].value.trim() : ""));
        });
        ["discard", "see_artist", "intl_override"].forEach(k => {
            params.append(k, (fieldInputs[k] && fieldInputs[k].checked) ? "1" : "0");
        });
    
        // DEBUG: Log what's being sent
        console.log("JRPD: [DEBUG] Sending update_song_vars request (from results panel)");
        console.log("JRPD: [DEBUG] songKey:", songKey);
        console.log("JRPD: [DEBUG] params:", params.toString());
    
        reviewFetch(getReviewServerUrl() + '/update_song_vars', {
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
                overlay2.remove();
                reviewLastMtime = 0;
                fetchResultsFile(); // Refresh the results panel to show updated values
            } else {
                showToast("Update failed: " + (res.msg || "unknown error"), "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: update_song_vars failed", e);
            showToast("Update failed", "#c62828");
            overlay2.remove();
        });
    };
    
    modal2.appendChild(form);
    overlay2.appendChild(modal2);
    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(overlay2);
}