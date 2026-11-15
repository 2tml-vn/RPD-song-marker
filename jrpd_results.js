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

// ---- Start button: launches the pipeline via the jrpd:// protocol handler ----
// Windows maps jrpd:// to D:\rpd\jrpd_protocol.py (see setup_protocol.bat),
// which runs label_marks_complete.py in a console window. The page itself is
// never navigated away - the browser shows a one-time "Open jrpd?" allow popup.
let jrpdStartClickedAt = 0;
const JRPD_START_GRACE_MS = 180000; // keep "⏳ Starting…" for 3 min before reverting

function jrpdCurrentVideoId() {
    // The marker loop keeps `vid` (jrpd_state.js) fresh every second; fall back
    // to parsing the URL ourselves (the button can be clicked before that tick).
    try {
        if (typeof vid !== "undefined" && vid) return vid;
    } catch (e) {}
    const hostname = window.location.hostname;
    if (hostname.includes("youtube.com")) {
        return new URLSearchParams(window.location.search).get("v");
    }
    if (hostname.includes("bilibili.com")) {
        const m = window.location.pathname.match(/\/video\/(BV[0-9A-Za-z]+|av\d+|\d+)/);
        if (!m) return null;
        const p = parseInt(new URLSearchParams(window.location.search).get("p"), 10);
        return (!isNaN(p) && p > 1) ? `${m[1]}_p${p}` : m[1];
    }
    return null;
}

function jrpdStartPending() {
    return jrpdStartClickedAt !== 0 && (Date.now() - jrpdStartClickedAt) < JRPD_START_GRACE_MS;
}

/**
 * Reflect the server connection state on the Start button.
 * Online: the button hides (the panel itself shows live status).
 * Offline: visible; reads "⏳ Starting…" while a launch request is pending.
 * @param {boolean} serverOnline - True when port 5000 answered a poll
 */
function updateStartBtn(serverOnline) {
    const btn = document.getElementById("jrpd-start-btn");
    if (!btn) return;
    if (serverOnline) {
        btn.style.display = "none";
        return;
    }
    const pending = jrpdStartPending();
    btn.style.display = "";
    btn.textContent = pending ? "⏳ Starting…" : "▶ Start";
    btn.style.background = pending ? "#ef6c00" : "#2e7d32";
}

function jrpdStartClicked() {
    const btn = document.getElementById("jrpd-start-btn");
    if (jrpdStartPending()) {
        showToast("Still starting… waiting for the JRPD server (port 5000)", "#ef6c00");
        return;
    }
    const vidId = jrpdCurrentVideoId();
    if (!vidId) {
        showToast("Cannot start: no video ID on this page", "#f44336");
        return;
    }
    jrpdStartClickedAt = Date.now();
    if (btn) updateStartBtn(false);
    // Anchor click → external protocol launch; the page does not navigate.
    try {
        const a = document.createElement("a");
        a.href = "jrpd://" + encodeURIComponent(vidId);
        document.body.appendChild(a);
        a.click();
        a.remove();
        showToast(`Launch requested: python label_marks_complete.py ${vidId}`, "#2e7d32");
    } catch (e) {
        jrpdStartClickedAt = 0;
        if (btn) updateStartBtn(false);
        showToast("Could not open the jrpd:// handler", "#f44336");
    }
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
            fetchResultsFile();
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
 * Show a raw text editor for a result row: edit the literal text stored on the
 * results.txt line (saved via /update_result, like other row-text fixes).
 * Saving also clears the row's 🚩 flag (explicit fix semantics, server-side).
 * @param {string} ts - Timestamp of the row
 * @param {string} currentText - Current row text (already flag-stripped)
 */
function showRawRowEditForm(ts, currentText) {
    if (!ts) return;

    const overlay = document.createElement("div");
    overlay.className = "jrpd-modal-overlay";
    overlay.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10000; display: flex; align-items: center; justify-content: center;";

    const modal = document.createElement("div");
    modal.style.cssText = "background: #2a2a3e; color: #eee; padding: 20px; border-radius: 10px; width: 640px; max-width: 90vw; max-height: 80vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.8);";

    const title = document.createElement("h3");
    title.textContent = `RAW Edit Row: ${ts}`;
    title.style.marginTop = "0";
    title.style.color = "#82b1ff";
    modal.appendChild(title);

    // The literal text of the line in results.txt (timestamp + flag excluded)
    const textInput = document.createElement("textarea");
    textInput.rows = 3;
    textInput.value = currentText || "";
    textInput.placeholder = "Row text as written on results.txt";
    textInput.style.cssText = "width: 100%; box-sizing: border-box; padding: 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; font-size: 12px; resize: vertical;";
    modal.appendChild(textInput);

    const hint = document.createElement("div");
    hint.style.cssText = "color: #888; font-size: 11px; margin-top: 4px;";
    hint.textContent = "Writes exactly this text to the results.txt line. If the row was 🚩 flagged, the flag is cleared (treated as a manual fix).";
    modal.appendChild(hint);

    const buttonsDiv = document.createElement("div");
    buttonsDiv.style.cssText = "display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px;";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = "padding: 8px 16px; background: #757575; color: white; border: none; border-radius: 4px; cursor: pointer;";
    cancelBtn.onclick = () => overlay.remove();

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Save";
    saveBtn.style.cssText = "padding: 8px 16px; background: #2e7d32; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;";
    saveBtn.onclick = () => {
        const newText = (textInput.value || "").replace(/\r?\n/g, " ").trim();
        reviewFetch(getReviewServerUrl() + `/update_result?ts=${encodeURIComponent(ts)}&song=${encodeURIComponent(newText)}&old_song=${encodeURIComponent(currentText || "")}`)
        .then(r => r.json())
        .then(res => {
            overlay.remove();
            if (res.replaced) {
                showToast(`${ts} raw text saved`, "#2e7d32");
                reviewLastMtime = 0;
                fetchResultsFile();
            } else {
                showToast("Raw edit failed — timestamp not found", "#c62828");
            }
        })
        .catch(e => {
            console.error("JRPD: raw row edit failed", e);
            showToast("Raw edit failed", "#c62828");
            overlay.remove();
        });
    };

    buttonsDiv.appendChild(cancelBtn);
    buttonsDiv.appendChild(saveBtn);
    modal.appendChild(buttonsDiv);

    // Ctrl+Enter saves, Escape cancels
    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.stopPropagation(); overlay.remove(); }
        else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveBtn.click(); }
    });

    overlay.appendChild(modal);
    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(overlay);
    textInput.focus();
}

/**
 * Build the RAW edit button for a resolved results row.
 * Shared by the row builder and the incremental row updater.
 * @param {string} ts - Timestamp of the row
 * @param {string} songText - Current row text (used as the editor's initial value)
 * @returns {HTMLElement} The raw edit button
 */
function createRawEditButton(ts, songText) {
    const rawBtn = document.createElement("button");
    rawBtn.textContent = "RAW";
    rawBtn.setAttribute("data-raw-edit", "1");
    rawBtn.title = "Edit the raw text of this row as stored on results.txt";
    rawBtn.style.cssText = "padding: 2px 4px; background: #444; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 9px; flex-shrink: 0;";
    rawBtn.onmouseenter = () => { rawBtn.style.background = "#555"; };
    rawBtn.onmouseleave = () => { rawBtn.style.background = "#444"; };
    rawBtn.onclick = (e) => {
        e.stopPropagation();
        showRawRowEditForm(ts, songText);
    };
    return rawBtn;
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
            fetchResultsFile();
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
            try { jrpdSetLatestIdent(ts, true); } catch (e) {}
            // Suppress the auto-detection duplicate (poll will see the same resolved value)
            try { if (jrpdPrevResultsMap) jrpdPrevResultsMap[ts] = res.song; } catch (e) {}
            if (res.detail) showAcrDetailModal(ts, res.detail, res.candidates, true);
            reviewLastMtime = 0;
            fetchResultsFile();
        } else if (res.status === "ok" && !res.identified) {
            try { jrpdSetLatestIdent(ts, false); } catch (e) {}
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

// ---- Background re-identify jobs (one at a time) ----
// ts -> jobId while a job runs. The slot is occupied as "pending" the
// moment a start request is fired, so a re-rendered row can never
// double-start a job.
const identifyJobsByTs = {};

/**
 * Ts of the row whose re-identify job is currently running, or null.
 * The registry holds at most one entry (one job at a time).
 * @returns {string|null}
 */
function identifyActiveJobTs() {
    for (const ts in identifyJobsByTs) return ts;
    return null;
}

/**
 * Render a re-identify button's state from the job registry: the running
 * row's button is busy ⏳ and clicking it cancels the job, every other
 * row's button is disabled until the job ends (one job at a time).
 * @param {HTMLElement} btn - The .acrBtn button (must carry data-acr-ts)
 * @param {string} ts - Timestamp of the row the button belongs to
 */
function applyAcrBtnState(btn, ts) {
    const activeTs = identifyActiveJobTs();
    if (activeTs === ts) {
        btn.dataset.busy = "1";
        btn.textContent = "⏳";
        btn.title = `Cancel re-identify (${ts})`;
        btn.style.opacity = "1";
        btn.disabled = false; // clickable = cancel
    } else if (activeTs) {
        btn.dataset.busy = "";
        btn.textContent = "🔍";
        btn.title = `Wait for ${activeTs} to finish`;
        btn.style.opacity = "0.7";
        btn.disabled = true;
    } else {
        btn.dataset.busy = "";
        btn.textContent = "🔍";
        btn.title = `Re-identify with Shazam + AHA + ACRCloud (${ts})`;
        btn.style.opacity = "0.7";
        btn.disabled = false;
    }
}

/**
 * Re-apply the registry state to every live re-identify button. Rows may
 * be re-rendered while a job runs (auto-detect poll), so job start/end
 * must refresh buttons instead of trusting one captured element.
 */
function refreshAcrButtons() {
    document.querySelectorAll(".acrBtn[data-acr-ts]").forEach(btn => {
        applyAcrBtnState(btn, btn.getAttribute("data-acr-ts"));
    });
}

/**
 * Re-identify a result row with all 3 engines (Shazam + AHA + ACRCloud).
 * The job runs in the background — no blocking panel; the page (and the
 * video) stay fully usable. When the job finishes, the video is paused
 * and the results modal pops up (pollIdentifyAllJob). Uses the server's
 * local audio file; nothing is written until the user chooses a result
 * (applied via /update_result).
 * @param {string} ts - Timestamp of the row to identify
 * @param {HTMLElement} [btn] - The button element (busy while the job runs)
 */
function identifyRowWithAll(ts, btn) {
    if (!ts) return;
    // One job at a time; also blocks a second start while the first
    // request is still in flight ("pending" occupies the registry slot).
    if (identifyActiveJobTs()) return;
    identifyJobsByTs[ts] = "pending";
    refreshAcrButtons();
    showToast(`Re-identifying ${ts} in background…`, "#1565c0");
    reviewFetch(getReviewServerUrl() + `/identify_all_start?ts=${encodeURIComponent(ts)}`)
    .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
    })
    .then(res => {
        if (res.status === "ok" && res.job) {
            if (identifyJobsByTs[ts] !== "pending") {
                // Cancelled while the start request was in flight —
                // also cancel the freshly created server job.
                reviewFetch(getReviewServerUrl() + `/identify_all_cancel?job=${encodeURIComponent(res.job)}`).catch(() => {});
                return;
            }
            identifyJobsByTs[ts] = res.job;
            pollIdentifyAllJob(ts, res.job);
        } else {
            showToast("Identify failed: " + (res.msg || "unknown error"), "#c62828");
            delete identifyJobsByTs[ts];
            refreshAcrButtons();
        }
    })
    .catch(e => {
        console.error("JRPD: identify_all_start failed", e);
        const msg = String((e && e.message) || e);
        if (msg.includes("404")) {
            showToast("identify_all endpoint missing — restart python server", "#c62828");
        } else {
            showToast(`Identify failed for ${ts}`, "#c62828");
        }
        delete identifyJobsByTs[ts];
        refreshAcrButtons();
    });
}

/**
 * Poll a background /identify_all job with no UI — the page stays fully
 * usable while it runs. When the job finishes, the video is paused and
 * the results modal pops up (the only moment the video pauses); errors
 * and cancellations only toast. Cancellation goes through the busy row
 * button (cancelIdentifyJob): once the registry no longer holds this
 * jobId, polling stops silently.
 * @param {string} ts - Timestamp of the row
 * @param {string} jobId - Job id from /identify_all_start
 */
function pollIdentifyAllJob(ts, jobId) {
    let finished = false;
    let failures = 0; // consecutive failed polls before giving up (6 x 500ms)

    const end = () => {
        if (finished) return;
        finished = true;
        clearInterval(timer);
        // Job is over (or gone): free the registry slot and re-render all
        // live buttons from it — covers a row button detached mid-job by
        // a results re-render.
        if (identifyJobsByTs[ts] === jobId) delete identifyJobsByTs[ts];
        refreshAcrButtons();
    };

    const timer = setInterval(() => {
        if (finished) return;
        if (identifyJobsByTs[ts] !== jobId) { end(); return; } // cancelled
        reviewFetch(getReviewServerUrl() + `/identify_all_job?job=${encodeURIComponent(jobId)}`)
        .then(r => {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
        })
        .then(js => {
            if (finished) return;
            if (js.status !== "ok") throw new Error(js.msg || "unknown job");
            failures = 0;
            if (js.job_error) {
                end();
                showToast("Identify failed: " + js.job_error, "#c62828");
            } else if (js.cancelled) {
                end(); // user cancelled — nothing left to show
            } else if (js.done && js.results) {
                end();
                // The one moment the video pauses: the results panel is up.
                jrpdPauseVideoForResults();
                showIdentifyAllModal(ts, js.results);
            } else if (js.done) {
                end();
                showToast("Identify failed: no results", "#c62828");
            }
        })
        .catch(e => {
            failures++;
            // Tolerate transient blips; give up after ~3s of them.
            if (failures >= 6) {
                end();
                console.error("JRPD: identify_all_job poll failed", e);
                showToast(`Identify failed for ${ts}`, "#c62828");
            }
        });
    }, 500);
}

/**
 * Pause the page video so the re-identify results modal can be reviewed
 * with the video frozen. Only called on the final results path — errors
 * and cancellations never pause.
 */
function jrpdPauseVideoForResults() {
    try {
        const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
        if (video && !video.paused) video.pause();
    } catch (e) {
        console.error("JRPD: pause video for results failed", e);
    }
}

/**
 * Cancel a running background identify job (click on the busy ⏳ button).
 * @param {string} ts - Timestamp of the row whose job is running
 */
function cancelIdentifyJob(ts) {
    const jobId = identifyJobsByTs[ts];
    if (!jobId || jobId === "pending") return; // nothing cancellable yet
    reviewFetch(getReviewServerUrl() + `/identify_all_cancel?job=${encodeURIComponent(jobId)}`).catch(() => {});
    delete identifyJobsByTs[ts];
    showToast(`Re-identify cancelled (${ts})`, "#f57c00");
    refreshAcrButtons(); // also stops the poller via its registry check
}

/**
 * Apply a chosen engine result to a row via the server.
 * @param {string} ts - Timestamp of the row
 * @param {string} song - Resolved song display text to write
 * @param {string} source - Engine label (shazam/aha/acrcloud) for the toast
 * @param {HTMLElement} [overlay] - Modal overlay to close on success
 */
function applyIdentifyChoice(ts, song, source, overlay) {
    if (!ts || !song) return;
    let oldSong = "";
    const row = document.querySelector(`[data-result-row][data-row-ts="${ts}"]`);
    if (row) {
        const songSpan = row.querySelector(".songContainer span[title]");
        if (songSpan) oldSong = songSpan.title || songSpan.textContent.trim();
    }
    reviewFetch(getReviewServerUrl() + `/update_result?ts=${encodeURIComponent(ts)}&song=${encodeURIComponent(song)}&old_song=${encodeURIComponent(oldSong)}`)
    .then(r => r.json())
    .then(res => {
        if (res.replaced) {
            unflagRow(ts);
            jrpdNotifyIdentPopup(jrpdBuildIdentPopupText(ts, song), true);
            try { jrpdSetLatestIdent(ts, true); } catch (e) {}
            // Suppress the auto-detection duplicate (poll will see the same resolved value)
            try { if (jrpdPrevResultsMap) jrpdPrevResultsMap[ts] = song; } catch (e) {}
            showToast(`${ts} set via ${source}`, "#2e7d32");
            if (overlay) overlay.remove();
            reviewLastMtime = 0;
            fetchResultsFile();
        } else {
            showToast("Apply failed — timestamp not found", "#c62828");
        }
    })
    .catch(e => {
        console.error("JRPD: apply identify choice failed", e);
        showToast("Apply failed", "#c62828");
    });
}

/**
 * Show a modal with the 3 engine results for a row.
 * Each engine card shows its DB-resolved song (if any) plus the raw
 * recognition, and a "Use this" button to apply that engine's song.
 * @param {string} ts - Timestamp of the row
 * @param {Object} results - {shazam, aha, acrcloud} payloads from /identify_all
 */
function showIdentifyAllModal(ts, results) {
    try {
        document.querySelectorAll(".jrpd-identall-modal-overlay").forEach(el => el.remove());
        const order = [
            ["shazam", "🎵 Shazam", "#ab47bc"],
            ["aha", "🅰️ AHA Music", "#26a69a"],
            ["acrcloud", "☁️ ACRCloud", "#42a5f5"],
        ];
        const overlay = document.createElement("div");
        overlay.className = "jrpd-identall-modal-overlay";
        overlay.style.cssText = "position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 10001; display: flex; align-items: center; justify-content: center;";

        const modal = document.createElement("div");
        modal.style.cssText = "background: #1e1e30; color: #eee; padding: 18px 20px; border-radius: 10px; min-width: 420px; max-width: 600px; max-height: 84vh; overflow-y: auto; box-shadow: 0 4px 24px rgba(0,0,0,0.8); font-size: 12px; line-height: 1.6;";

        const title = document.createElement("h3");
        title.style.cssText = "margin: 0 0 10px 0; color: #82b1ff; font-size: 14px;";
        title.textContent = `🔍 Re-identify — ${ts} (pick one)`;
        modal.appendChild(title);

        order.forEach(([key, label, color]) => {
            const r = (results && results[key]) || {};
            const card = document.createElement("div");
            card.style.cssText = `border: 1px solid ${color}; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: #23233a;`;

            const head = document.createElement("div");
            head.style.cssText = `font-weight: bold; font-size: 13px; color: ${color}; margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center; gap: 8px;`;
            const nameSpan = document.createElement("span");
            nameSpan.textContent = label;
            head.appendChild(nameSpan);
            const badge = document.createElement("span");
            if (r.disabled) {
                badge.textContent = "disabled";
                badge.style.cssText = "font-size: 10px; color: #888; border: 1px solid #555; border-radius: 3px; padding: 1px 6px;";
            } else if (r.song) {
                badge.textContent = `match (w${r.window || "?"})`;
                badge.style.cssText = "font-size: 10px; color: #fff; background: #2e7d32; border-radius: 3px; padding: 1px 6px;";
            } else if (r.blocked === "rate_limited") {
                badge.textContent = "⏸ rate-limited (429)";
                badge.style.cssText = "font-size: 10px; color: #000; background: #ffb74d; border-radius: 3px; padding: 1px 6px;";
            } else if (r.blocked === "quota_exceeded") {
                badge.textContent = "⛔ quota exceeded (3003)";
                badge.style.cssText = "font-size: 10px; color: #fff; background: #e57373; border-radius: 3px; padding: 1px 6px;";
            } else if (r.raw_title || (r.detail && (r.detail.title || r.detail.artist))) {
                badge.textContent = "raw only (no DB match)";
                badge.style.cssText = "font-size: 10px; color: #000; background: #ffb74d; border-radius: 3px; padding: 1px 6px;";
            } else {
                badge.textContent = "no match";
                badge.style.cssText = "font-size: 10px; color: #ccc; border: 1px solid #555; border-radius: 3px; padding: 1px 6px;";
            }
            head.appendChild(badge);
            card.appendChild(head);

            const songLine = document.createElement("div");
            songLine.style.cssText = "font-weight: bold; color: #fff; margin-bottom: 2px; user-select: text;";
            songLine.textContent = r.song
                || (r.blocked === "rate_limited" ? "(rate-limited — endpoint returned 429, not queried)"
                    : r.blocked === "quota_exceeded" ? "(quota exceeded — ACRCloud: requests limit exceeded)"
                    : "(no database match)");
            if (!r.song) songLine.style.color = "#888";
            card.appendChild(songLine);

            const rawTitle = r.raw_title || (r.detail && r.detail.title) || "?";
            const rawArtist = r.raw_artist || (r.detail && r.detail.artist) || "?";
            const rawLine = document.createElement("div");
            rawLine.style.cssText = "color: #aaa; margin-bottom: 4px; user-select: text;";
            rawLine.textContent = `raw: ${rawTitle} - ${rawArtist}`;
            card.appendChild(rawLine);

            const d = r.detail || {};
            const extras = [];
            if (d.album) extras.push(`album: ${d.album}`);
            if (d.score != null) extras.push(`score: ${d.score}`);
            if (d.release_date) extras.push(`release: ${d.release_date}`);
            if (d.play_offset_ms != null) extras.push(`offset: ${d.play_offset_ms}ms`);
            if (extras.length) {
                const exLine = document.createElement("div");
                exLine.style.cssText = "color: #888; font-size: 11px; margin-bottom: 6px; user-select: text;";
                exLine.textContent = extras.join(" · ");
                card.appendChild(exLine);
            }

            const btnBar = document.createElement("div");
            btnBar.style.cssText = "display: flex; gap: 8px; justify-content: flex-end; margin-top: 6px;";

            const copyBtn = document.createElement("button");
            copyBtn.textContent = "📋 Copy";
            copyBtn.style.cssText = "padding: 5px 12px; background: #0f3460; color: white; border: none; border-radius: 4px; cursor: pointer;";
            copyBtn.onclick = () => {
                const lines = [
                    r.song ? `Song: ${r.song}` : null,
                    `Raw: ${rawTitle} - ${rawArtist}`,
                    d.album ? `Album: ${d.album}` : null,
                    d.release_date ? `Release: ${d.release_date}` : null,
                    d.score != null ? `Score: ${d.score}` : null,
                ].filter(Boolean).join("\n");
                try {
                    navigator.clipboard.writeText(lines || `${rawTitle} - ${rawArtist}`).then(() => showToast(`${label} copied`, "#2e7d32"));
                } catch (e) {
                    console.warn("JRPD: copy failed", e);
                }
            };
            btnBar.appendChild(copyBtn);

            const useBtn = document.createElement("button");
            useBtn.textContent = r.song ? `✅ Use this (${key})` : "✅ Use this";
            useBtn.title = r.song ? `Write "${r.song}" to ${ts}` : "No database match to apply";
            useBtn.disabled = !r.song;
            useBtn.style.cssText = `padding: 5px 12px; background: ${r.song ? "#2e7d32" : "#444"}; color: ${r.song ? "white" : "#888"}; border: none; border-radius: 4px; cursor: ${r.song ? "pointer" : "not-allowed"}; font-weight: bold;`;
            if (r.song) {
                useBtn.onclick = () => applyIdentifyChoice(ts, r.song, key, overlay);
            }
            btnBar.appendChild(useBtn);
            card.appendChild(btnBar);

            modal.appendChild(card);
        });

        const hint = document.createElement("div");
        hint.style.cssText = "color: #888; font-size: 11px; margin-bottom: 10px;";
        hint.textContent = "Nothing is written until you press “Use this”. Raw-only results need a manual add via ➕.";
        modal.appendChild(hint);

        const footBar = document.createElement("div");
        footBar.style.cssText = "display: flex; gap: 8px; justify-content: flex-end;";
        const closeBtn = document.createElement("button");
        closeBtn.textContent = "Close";
        closeBtn.style.cssText = "padding: 6px 14px; background: #555; color: white; border: none; border-radius: 4px; cursor: pointer;";
        closeBtn.onclick = () => overlay.remove();
        footBar.appendChild(closeBtn);
        modal.appendChild(footBar);

        overlay.appendChild(modal);
        overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) overlay.remove(); });
        (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(overlay);
    } catch (e) {
        console.error("JRPD: showIdentifyAllModal failed", e);
    }
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
    panel.style.cssText = "position: fixed; min-width: 280px; min-height: 200px; background: #1a1a2e; color: #eee; z-index: 9999; padding: 0; border-radius: 10px; box-shadow: 0 4px 24px rgba(0,0,0,0.6); display: none; flex-direction: column; font-family: Roboto, Arial, sans-serif; border: 1px solid #333; resize: none; overflow: hidden;";

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

    // Start button (visible only while the JRPD server is offline)
    const startBtn = document.createElement("button");
    startBtn.id = "jrpd-start-btn";
    startBtn.title = "Start the pipeline for this video (jrpd:// → opens a console window)";
    startBtn.style.cssText = "padding: 2px 8px; background: #2e7d32; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; font-weight: bold; display: none;";
    startBtn.textContent = "▶ Start";
    startBtn.onclick = jrpdStartClicked;
    controlsGroup.appendChild(startBtn);

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

    const quitBtn = document.createElement("button");
    quitBtn.textContent = "Quit";
    quitBtn.title = "Quit: stops the Python process, deletes local audio (results.txt / progress.json kept)";
    quitBtn.style.cssText = "padding: 2px 8px; background: #c62828; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; font-weight: bold;";
    quitBtn.onclick = () => {
        if (!confirm("Quit session and delete the local audio file?\n(results.txt, progress.json and unidentified.json are kept)")) return;
        // Save panel position, then the same teardown as Done: disarm gap loops.
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
        isReviewMode = false;
        closeResultsPanel();
        reviewFetch(getReviewServerUrl() + "/quit_session")
            .then(() => showToast("Session quit — local audio deleted", "#c62828"))
            .catch(() => showToast("Quit failed (server not reachable?)", "#f44336"));
    };
    controlsGroup.appendChild(quitBtn);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.title = "Hide panel (reopen anytime with 📋)";
    closeBtn.style.cssText = "padding: 2px 6px; background: #333; color: #ccc; border: none; border-radius: 3px; cursor: pointer; font-size: 11px;";
    closeBtn.onclick = () => closeResultsPanel();
    controlsGroup.appendChild(closeBtn);

    header.appendChild(controlsGroup);
    panel.appendChild(header);

    // Action toolbar (UNDO / MARK / FINISH) — mirrors the player control-bar
    // buttons so marking works even when the control bar is hidden.
    const actionBar = document.createElement("div");
    actionBar.style.cssText = "display: flex; gap: 6px; padding: 6px 10px; border-bottom: 1px solid #333; background: #16213e; flex-shrink: 0;";

    const mkActionBtn = (text, bgColor, onClick) => {
        const btn = document.createElement("button");
        btn.textContent = text;
        btn.style.cssText = `flex: 1; padding: 4px 10px; background: ${bgColor}; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold;`;
        btn.onclick = () => { if (typeof onClick === "function") onClick(); };
        return btn;
    };

    actionBar.appendChild(mkActionBtn("UNDO",
        "#c62828", () => { if (typeof doUndo === "function") doUndo(); }));
    actionBar.appendChild(mkActionBtn("MARK",
        "#2e7d32", () => { if (typeof doMark === "function") doMark(); }));
    actionBar.appendChild(mkActionBtn("FINISH",
        "#6200ea", () => { if (typeof doFinish === "function") doFinish(); }));
    panel.appendChild(actionBar);

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

    // If a full rebuild was deferred while the pointer was over the list
    // (to avoid eating an in-flight click), flush it once the pointer leaves.
    list.addEventListener("mouseleave", () => {
        if (typeof jrpdFlushPendingRerender === "function") jrpdFlushPendingRerender(true);
    });

    // Track a press physically in flight anywhere in the list (mousedown..
    // mouseup). Capture phase so a child's stopPropagation can't hide it;
    // window-level release handles the pointer leaving mid-press.
    const jrpdMarkListPointerDown = (e) => { jrpdListPointerDown = true; };
    const jrpdMarkListPointerUp = () => { jrpdListPointerDown = false; };
    list.addEventListener("pointerdown", jrpdMarkListPointerDown, true);
    window.addEventListener("pointerup", jrpdMarkListPointerUp, true);
    window.addEventListener("pointercancel", jrpdMarkListPointerUp, true);

    // Make panel available during marking by default (unless explicitly closed)
    const isVisibleByDefault = prefs.panelVisible !== false;
    panel.style.display = isVisibleByDefault ? "flex" : "none";

    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(panel);
    // Directional resize: drag any edge or corner (w/n move position, e/s grow size).
    try {
        if (typeof jrpdEnableDirectionalResize === "function") {
            jrpdEnableDirectionalResize(panel, {
                minWidth: 280,
                minHeight: 200,
                onResizeEnd: (r) => savePanelPrefs({ width: r.width, height: r.height, left: r.left, top: r.top })
            });
        }
    } catch (e) {}
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
    const next = new Set(parsed.filter(e => e.flagged).map(e => e.ts));
    // This runs on every render (i.e. at least once per poll tick). Skip the
    // reassign + synchronous localStorage write when nothing actually changed.
    let same = next.size === flaggedTimestamps.size;
    if (same) {
        for (const t of next) {
            if (!flaggedTimestamps.has(t)) { same = false; break; }
        }
    }
    if (same) return;
    flaggedTimestamps = next;
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
        jrpdLatestIdentTs = null;
        jrpdLatestIdentOk = false;
        jrpdLatestIdentNeedsScroll = false;
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
 * Style a row as the latest identification (success = green, fail = orange).
 * Uses background + left border + glow so it stays distinct from the
 * yellow selection outline and the red/grey default row colors.
 * @param {HTMLElement} row - Result row element
 * @param {boolean} ok - True for success, false for fail
 * @returns {void}
 */
function jrpdStyleRowAsLatest(row, ok) {
    if (!row) return;
    row.setAttribute("data-jrpd-latest", ok ? "ok" : "fail");
    if (ok) {
        row.style.background = "#1d3b2a";
        row.style.borderLeft = "3px solid #4caf50";
        row.style.boxShadow = "0 0 0 1px #4caf50, 0 0 10px rgba(76,175,80,0.55)";
    } else {
        row.style.background = "#3a2415";
        row.style.borderLeft = "3px solid #ff9800";
        row.style.boxShadow = "0 0 0 1px #ff9800, 0 0 10px rgba(255,152,0,0.55)";
    }
}

/**
 * Restore a row to its default (non-latest) colors based on content.
 * @param {HTMLElement} row - Result row element
 * @returns {void}
 */
function jrpdClearRowLatestStyle(row) {
    if (!row) return;
    row.removeAttribute("data-jrpd-latest");
    row.style.boxShadow = "";
    const isGap = row.querySelector(".gapLabel") !== null;
    const songSpan = row.querySelector(".songContainer span[title]");
    const isProcessing = !!songSpan && (songSpan.title === "Processing..." || /Identifying/.test(songSpan.textContent || ""));
    if (isGap) {
        row.style.background = "#2a1a1a";
        row.style.borderLeft = "3px solid #ff5252";
    } else if (isProcessing) {
        row.style.background = "#232015";
        row.style.borderLeft = "3px solid #ffb74d";
    } else {
        row.style.background = "#1e1e30";
        row.style.borderLeft = "none";
    }
}

/**
 * Record the latest identification and highlight its row.
 * Only one row is highlighted at a time; previous highlight is cleared.
 * @param {string} ts - Timestamp of the identified row
 * @param {boolean} ok - True for success, false for fail
 * @param {boolean} [scroll=true] - Scroll the row into view
 * @returns {void}
 */
function jrpdSetLatestIdent(ts, ok, scroll = true) {
    try {
        if (!ts) return;
        jrpdLatestIdentTs = ts;
        jrpdLatestIdentOk = !!ok;
        try { jrpdLatestIdentNeedsScroll = !scroll; } catch (e) {}
        const list = document.getElementById("jrpd-results-list");
        if (!list) return;
        list.querySelectorAll("[data-jrpd-latest]").forEach(r => {
            if (r.getAttribute("data-row-ts") !== ts) jrpdClearRowLatestStyle(r);
        });
        const row = list.querySelector(`[data-row-ts="${ts}"]`);
        if (row) {
            jrpdStyleRowAsLatest(row, !!ok);
            if (scroll) {
                try { row.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (e) {}
            }
        }
    } catch (e) {
        console.warn("JRPD: set latest ident failed", e);
    }
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
        const justResolved = [];
        Object.keys(newMap).forEach(ts => {
            const prev = prevMap[ts];
            const cur = newMap[ts];
            // Brand-new ts that arrived already resolved (e.g. after reload): skip, not a fresh identification.
            if (prev === "Processing..." && cur !== "Processing...") {
                jrpdNotifyIdentPopup(jrpdBuildIdentPopupText(ts, cur), !!cur);
                justResolved.push(ts);
            }
        });
        if (justResolved.length) {
            // Highlight the chronologically latest resolved row when several
            // finish in the same poll.
            let latestTs = justResolved[0];
            try {
                if (typeof parseTimestampToSeconds === "function") {
                    latestTs = justResolved.slice().sort((a, b) => parseTimestampToSeconds(a) - parseTimestampToSeconds(b)).pop();
                }
            } catch (e) {}
            jrpdSetLatestIdent(latestTs, !!newMap[latestTs], false);
        }
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
        row.style.boxShadow = "";
    } else {
        songSpan.textContent = resolvedSong;
        songSpan.title = resolvedSong;
        songSpan.style.color = "#ccc";
        songSpan.style.fontStyle = "normal";
        row.style.background = "#1e1e30";
        row.style.borderLeft = "none";
        row.style.boxShadow = "";
    }
    // Preserve latest-identification highlight (it uses bg/border/glow too).
    try {
        const ts = row.getAttribute("data-row-ts");
        if (typeof jrpdLatestIdentTs !== "undefined" && jrpdLatestIdentTs === ts) {
            jrpdStyleRowAsLatest(row, !!jrpdLatestIdentOk);
        } else {
            row.removeAttribute("data-jrpd-latest");
        }
    } catch (e) {}
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

        // A row that just resolved in-place needs the RAW text button added
        if (!isEffectiveProcessing && !songContainer.querySelector("button[data-raw-edit]")) {
            songContainer.appendChild(createRawEditButton(ts, effectiveSong));
        }
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
        if (typeof updateStartBtn === "function") updateStartBtn(true);
        jrpdDetectIdentifications(lines);
        renderResultsPanel(lines, { forceFullRender, preserveScroll });
    })
    .catch(e => {
        // Server may be starting up or not yet running
        if (typeof updateStartBtn === "function") updateStartBtn(false);
        const list = document.getElementById("jrpd-results-list");
        if (list && list.querySelectorAll("[data-result-row]").length === 0) {
            if (!list.querySelector(".jrpd-offline-msg")) {
                list.textContent = "";
                const msg = document.createElement("div");
                msg.className = "jrpd-offline-msg";
                msg.style.cssText = "color: #ffb74d; font-style: italic; text-align: center; padding: 24px 10px; font-size: 11px; line-height: 1.5;";
                msg.textContent = "⏳ Server offline — click ▶ Start in the panel header to launch the pipeline (or run python label_marks_complete.py manually).";
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

    // Insert just before the next chronologically larger row (O(log n) scan
    // for the position, then a single insertBefore). The old path cleared the
    // whole list and rebuilt every row, which barfed with large results lists.
    const allRows = Array.from(list.querySelectorAll("[data-result-row]"));
    const tNew = typeof parseTimestampToSeconds === "function" ? parseTimestampToSeconds(ts) : 0;
    let insertIdx = allRows.length;
    for (let i = 0; i < allRows.length; i++) {
        const t = parseTimestampToSeconds(allRows[i].getAttribute("data-row-ts"));
        if (t > tNew) { insertIdx = i; break; }
    }

    const row = createResultRow({ ts: ts, song: status, flagged: false });
    if (insertIdx < allRows.length) {
        allRows[insertIdx].parentNode.insertBefore(row, allRows[insertIdx]);
    } else {
        list.appendChild(row);
    }
    // The brand-new row is never flagged, so only stale-adjacent rows could
    // diverge; cheap single-row sync instead of rebuilding everything.
    const adj = allRows[insertIdx];
    if (adj && !adj.querySelector(".flagBadge") &&
        typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(adj.getAttribute("data-row-ts"))) {
        syncRowFlagInPlace(adj);
    }

    // Auto-scroll to newly added row
    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Update a row's flag UI in place when it diverges from flaggedTimestamps.
 * Avoids the previous "walk every row's flag badge after every insert" pass.
 * @param {HTMLElement} row - Row element to sync
 * @returns {void}
 */
function syncRowFlagInPlace(row) {
    if (!row) return;
    const ts = row.getAttribute("data-row-ts");
    const isFlagged = typeof flaggedTimestamps !== "undefined" && flaggedTimestamps.has(ts);
    const hasBadge = row.querySelector(".flagBadge") !== null;
    if (hasBadge === isFlagged) {
        // Also keep the flag button label in step when created before a flag landed.
        const flagBtn = row.querySelector(".flagBtn");
        if (flagBtn) {
            const want = isFlagged ? "🚩" : "🏳️";
            if (flagBtn.textContent !== want) {
                flagBtn.textContent = want;
                flagBtn.title = isFlagged ? "Unflag (done)" : "Flag for manual fix";
                flagBtn.style.background = isFlagged ? "#ffeb3b" : "transparent";
                flagBtn.style.opacity = isFlagged ? "1" : "0.45";
            }
        }
        return;
    }
    if (isFlagged) {
        const badge = document.createElement("span");
        badge.className = "flagBadge";
        badge.textContent = "🚩 CHECK";
        badge.style.cssText = "background: #ffeb3b; color: #000; font-weight: bold; padding: 1px 6px; border-radius: 3px; font-size: 10px; flex-shrink: 0; margin-left: auto; white-space: nowrap;";
        row.appendChild(badge);
    } else {
        const badge = row.querySelector(".flagBadge");
        if (badge) badge.remove();
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
    try {
        if (typeof jrpdLatestIdentTs !== "undefined" && jrpdLatestIdentTs === ts) {
            jrpdLatestIdentTs = null;
            jrpdLatestIdentOk = false;
            jrpdLatestIdentNeedsScroll = false;
        }
    } catch (e) {}
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
 * @param {Object} entry - The entry object with ts, song and flagged properties
 * @returns {HTMLElement} The row element
 */
function createResultRow(entry) {
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
    row.style.cssText = `padding: 4px 8px; margin-bottom: 2px; border-radius: 5px; font-size: ${reviewFontSize}px; display: flex; align-items: center; gap: 6px; transition: outline 0.15s; min-height: 24px; ${rowBg}`;

    if (reviewSelectedTs === entry.ts) {
        row.style.outline = "2px solid #ffeb3b";
        row.style.outlineOffset = "-1px";
    }

    // Row clicks are inert; the panel opens only via the ➕ button or the
    // ✏️ button on "Processing..." rows.

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

        // Loop end = next mark's ts, read from the live row order. Reading the
        // DOM (not a snapshot captured at row creation) stays correct after
        // per-row inserts/removes and partial renders.
        let endSec = video.duration;
        const nextRow = row.nextElementSibling;
        const nextTs = nextRow ? nextRow.getAttribute("data-row-ts") : null;
        if (nextTs) endSec = parseTimestampToSeconds(nextTs);

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

    // Re-identify button (all 3 engines: Shazam + AHA + ACRCloud, pick result).
    // The job runs in the background, one at a time: while this row's job
    // runs, clicking the ⏳ button cancels it; other rows' buttons are
    // disabled until it ends.
    const acrBtn = document.createElement("button");
    acrBtn.className = "acrBtn";
    acrBtn.setAttribute("data-acr-ts", entry.ts);
    acrBtn.style.cssText = "padding: 1px 4px; border: none; border-radius: 3px; cursor: pointer; font-size: 11px; flex-shrink: 0; background: transparent; opacity: 0.7;";
    applyAcrBtnState(acrBtn, entry.ts);
    acrBtn.onclick = (e) => {
        e.stopPropagation();
        if (acrBtn.dataset.busy === "1") {
            cancelIdentifyJob(entry.ts);
        } else {
            identifyRowWithAll(entry.ts, acrBtn);
        }
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

        // RAW edit button: edit the literal text stored on this results.txt line
        if (!isProcessing) {
            songContainer.appendChild(createRawEditButton(entry.ts, entry.song));
        }

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

    // Latest-identification highlight (survives full rebuilds)
    try {
        if (typeof jrpdLatestIdentTs !== "undefined" && jrpdLatestIdentTs === entry.ts) {
            jrpdStyleRowAsLatest(row, !!jrpdLatestIdentOk);
        }
    } catch (e) {}
    
    return row;
}

// Deferred full-rebuild state (see renderResultsPanel). A full rebuild sets
// list.textContent = "", detaching the button under the cursor; if that lands
// between mousedown and mouseup, the click is silently lost.
let jrpdPendingFullRerender = null;
let jrpdPendingRerenderTimer = null;
// True only while a press is physically in flight (mousedown..mouseup).
// A button that merely holds focus (e.g. the last clicked 🧹) is NOT an
// interaction — treating focus as "pointer present" used to keep the rebuild
// deferred forever, leaving server-side edits invisible in the panel.
let jrpdListPointerDown = false;
const JRPD_RERENDER_DEFER_MS = 700;
const JRPD_RERENDER_MAX_DEFER_MS = 2500;

function jrpdResultsListHasPointer() {
    try {
        const list = document.getElementById("jrpd-results-list");
        if (!list) return false;
        if (list.matches(":hover")) return true;
        // Press in flight: covers the "drag off the list mid-click" window,
        // where the click target still exists and must not be detached.
        if (jrpdListPointerDown) return true;
    } catch (e) {}
    return false;
}

function jrpdFlushPendingRerender(fromLeave) {
    if (jrpdPendingRerenderTimer) { clearTimeout(jrpdPendingRerenderTimer); jrpdPendingRerenderTimer = null; }
    const pending = jrpdPendingFullRerender;
    if (!pending) return;
    // Over the list and inside the deferral budget: re-arm instead of
    // rebuilding under a possibly in-flight click.
    if (jrpdResultsListHasPointer() && Date.now() - pending.firstDeferAt < JRPD_RERENDER_MAX_DEFER_MS) {
        jrpdPendingRerenderTimer = setTimeout(() => jrpdFlushPendingRerender(false), JRPD_RERENDER_DEFER_MS);
        return;
    }
    // Either the pointer left the list (safe to rebuild now) or the budget
    // expired (rebuild anyway). The pending object carries its own start time,
    // so this cap can never be reset by a later re-deferral: at worst the
    // panel rebuilds ~3s after the change even if the mouse never leaves.
    jrpdPendingFullRerender = null;
    renderResultsPanel(pending.lines, { forceFullRender: pending.forceFullRender, preserveScroll: pending.preserveScroll, noDefer: true });
}

function renderResultsPanel(lines, options = {}) {
    const { forceFullRender = false, preserveScroll = true } = options;
    const list = document.getElementById("jrpd-results-list");
    if (!list) {
        console.log("JRPD: [DEBUG] renderResultsPanel - list element not found");
        return;
    }

    // A deferred full rebuild is pending and the pointer has left the list:
    // fold it into this render (this call carries the latest lines).
    if (!jrpdResultsListHasPointer() && jrpdPendingFullRerender) {
        jrpdPendingFullRerender = null;
        if (jrpdPendingRerenderTimer) { clearTimeout(jrpdPendingRerenderTimer); jrpdPendingRerenderTimer = null; }
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
                    
                    // If gap status changed, rebuild just this row. A whole-list
                    // rebuild for a single row transition costs O(n) DOM churn on
                    // every resolution; swapping one row is room-temperature.
                    // Only defer when a press is actually in flight — detaching
                    // the row between mousedown and mouseup would eat the click.
                    // Merely hovering (even right after our own button click)
                    // is safe: that interaction already ended.
                    if (wasGap !== isNowGap) {
                        if (!jrpdListPointerDown) {
                            try {
                                row.replaceWith(createResultRow(entry));
                                return;
                            } catch (e) { /* fall through to full rebuild */ }
                        }
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
                    // A fresh identification just landed: bring its row into view once.
                    try {
                        if (typeof jrpdLatestIdentNeedsScroll !== "undefined" && jrpdLatestIdentNeedsScroll && jrpdLatestIdentTs) {
                            jrpdLatestIdentNeedsScroll = false;
                            const latestRow = list.querySelector(`[data-row-ts="${jrpdLatestIdentTs}"]`);
                            if (latestRow) {
                                jrpdStyleRowAsLatest(latestRow, !!jrpdLatestIdentOk);
                                latestRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
                                return;
                            }
                        }
                    } catch (e) {}
                    // Restore scroll position and return
                    if (preserveScroll) {
                        list.scrollTop = savedScrollTop;
                    }
                    return; // Done, no full rebuild needed
                }
            }
        }
    }
    
    // Full rebuild needed. This destroys every row button, so if it lands
    // between mousedown and mouseup on a button, no click event ever fires
    // and the user has to click a second time. Defer while the pointer is
    // over the list (or a press is in flight); in-place song-text updates
    // above have already been applied, so nothing goes visibly stale.
    // The pending object carries its own start time: the deferral cap is
    // NEVER reset, so a parked pointer still gets a rebuild after at most
    // ~JRPD_RERENDER_MAX_DEFER_MS + JRPD_RERENDER_DEFER_MS.
    if (jrpdResultsListHasPointer() && !options.noDefer) {
        const now = Date.now();
        if (!jrpdPendingFullRerender) {
            jrpdPendingFullRerender = { lines, forceFullRender, preserveScroll, firstDeferAt: now };
        } else {
            // A newer set of lines arrived while the rebuild is pending:
            // refresh the carried data, keep the original cap start time.
            jrpdPendingFullRerender.lines = lines;
            jrpdPendingFullRerender.forceFullRender = forceFullRender;
            jrpdPendingFullRerender.preserveScroll = preserveScroll;
        }
        if (now - jrpdPendingFullRerender.firstDeferAt < JRPD_RERENDER_MAX_DEFER_MS) {
            if (!jrpdPendingRerenderTimer) {
                jrpdPendingRerenderTimer = setTimeout(() => jrpdFlushPendingRerender(false), JRPD_RERENDER_DEFER_MS);
            }
            return;
        }
        // Cap expired while the pointer is still parked: fall through and
        // rebuild now (the flush timer cannot defer again, so this is how
        // every deferral loop terminates).
    }
    jrpdPendingFullRerender = null;
    list.textContent = "";

    parsed.forEach((entry) => {
        list.appendChild(createResultRow(entry));
    });

    // A fresh identification just landed: bring its row into view once
    // (overrides the preserved scroll for this render only).
    try {
        if (typeof jrpdLatestIdentNeedsScroll !== "undefined" && jrpdLatestIdentNeedsScroll && jrpdLatestIdentTs) {
            jrpdLatestIdentNeedsScroll = false;
            const latestRow = list.querySelector(`[data-row-ts="${jrpdLatestIdentTs}"]`);
            if (latestRow) {
                latestRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
                return;
            }
        }
    } catch (e) {}

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
        const isGapRow = !!(row && row.querySelector(".gapLabel"));
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
    // Parse the display string to prefill the form
    const displayParts = songDisplay.split(" - ");
    const songPart = displayParts[0] || "";
    const artistPart = displayParts[1] || "";

    // Resolve the row's display back to its true registration key.
    // Keys are raw engine titles now, so the display cannot be reliably parsed
    // here — ask the server to reverse-match (exact match over all known keys,
    // paren-strip-fallback otherwise).
    let songKey = songPart.trim();
    try {
        const resp = await reviewFetch(`${getReviewServerUrl()}/song_key_from_display?ts=${encodeURIComponent(timestamp)}&display=${encodeURIComponent(songDisplay.trim())}`);
        if (resp.ok) {
            const data = await resp.json();
            if (data && data.key) songKey = data.key;
        }
    } catch (e) {
        console.warn("JRPD: song_key_from_display failed, using display-derived key", e);
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

    // Song Key (editable — renaming moves fields to the new key and turns the
    // old key into a remap rule pointing at it)
    const keyLabel = document.createElement("label");
    keyLabel.textContent = "Song Key:";
    keyLabel.style.fontWeight = "bold";
    form.appendChild(keyLabel);

    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.value = songKey;
    keyInput.title = "Renaming this key: fields move to the new key and the old key becomes a remap rule for future identifications";
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
        // A changed key adds new_key: server renames the entry — fields move to
        // the new key, the old key becomes a remap rule, and rows owned by the
        // old key are rewritten to the new name (bindings re-labeled).
        const newKeyValue = keyInput.value.trim();
        const params = new URLSearchParams();
        params.append('key', songKey);
        params.append('ts', timestamp); // the row we clicked — exact row anchor for rewrites
        if (newKeyValue && newKeyValue !== songKey) {
            params.append('new_key', newKeyValue);
        }
        ["intl", "artist_orig", "artist_intl", "info", "remap"].forEach(k => {
            params.append(k, (fieldInputs[k] ? fieldInputs[k].value.trim() : ""));
        });
        ["discard", "see_artist", "intl_override"].forEach(k => {
            params.append(k, (fieldInputs[k] && fieldInputs[k].checked) ? "1" : "0");
        });
    
        // DEBUG: Log what's being sent
        console.log("JRPD: [DEBUG] Sending update_song_vars request (from results panel)");
        console.log("JRPD: [DEBUG] songKey:", songKey);
        console.log("JRPD: [DEBUG] newKeyValue:", newKeyValue);
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
                if (newKeyValue && newKeyValue !== songKey) {
                    showToast(`Renamed: ${songKey} → ${newKeyValue} (old key now remaps)`, "#2e7d32");
                } else {
                    showToast(`Updated song: ${songKey}`, "#2e7d32");
                }
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