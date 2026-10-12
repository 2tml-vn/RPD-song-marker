var serverBaseUrl;
var hostname;

/**
 * Get server URL based on platform
 * @returns {string} Server base URL
 */
function getServerUrl() {
    if (typeof jrpdGetServerBase === "function") return jrpdGetServerBase();
    const hostname = window.location.hostname;
    const biliHost = (typeof JRPD_BILIBILI_HOST !== "undefined") ? JRPD_BILIBILI_HOST : 'http://192.168.100.108:5000';
    const localHost = (typeof JRPD_LOCAL_HOST !== "undefined") ? JRPD_LOCAL_HOST : 'http://127.0.0.1:5000';
    return hostname.includes('bilibili.com') ? biliHost : localHost;
}

/**
 * Cross-platform fetch that uses GM_xmlhttpRequest for Bilibili to bypass CORS
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options
 * @returns {Promise} Promise with response
 */
function jrpdFetch(url, options = {}) {
    const hostname = window.location.hostname;
    const isBilibili = hostname.includes('bilibili.com');

    // Adjust URL for Bilibili to use LAN IP (central hosts from jrpd_state.js)
    let adjustedUrl = url;
    if (isBilibili) {
        const localHost = (typeof JRPD_LOCAL_HOST !== "undefined") ? JRPD_LOCAL_HOST : 'http://127.0.0.1:5000';
        const biliHost = (typeof jrpdGetServerBase === "function") ? jrpdGetServerBase()
            : ((typeof JRPD_BILIBILI_HOST !== "undefined") ? JRPD_BILIBILI_HOST : 'http://192.168.100.108:5000');
        adjustedUrl = url.replace(localHost, biliHost);
    }
    
    // Use GM_xmlhttpRequest when available to bypass CORS, mixed content, and loopback restrictions
    if (typeof GM_xmlhttpRequest !== 'undefined') {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: options.method || 'GET',
                url: adjustedUrl,
                data: options.body,
                headers: options.headers || {},
                onload: (response) => {
                    resolve({
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: () => {
                            try {
                                return Promise.resolve(JSON.parse(response.responseText));
                            } catch (e) {
                                return Promise.reject(e);
                            }
                        },
                        text: () => Promise.resolve(response.responseText)
                    });
                },
                onerror: (err) => reject(err),
                ontimeout: (err) => reject(err)
            });
        });
    } else {
        return fetch(adjustedUrl, options);
    }
}

/**
 * JRPD Utility Functions
 * Shared utilities for all JRPD modules
 * @module jrpd_utils
 */

/**
 * Extract Bilibili video key, including multi-part suffix.
 * ?p=2 (or missing/1) -> "BVxxx" stays bare for backward compat,
 * ?p=N (N>1) -> "BVxxx_pN" so parts get separate sessions.
 * @returns {string} Video key or 'default'
 */
function getBilibiliVideoKey() {
    const path = window.location.pathname;
    const match = path.match(/\/video\/(BV[0-9A-Za-z]+|av\d+|\d+)/);
    if (!match) return 'default';
    const base = match[1];
    try {
        const p = new URLSearchParams(window.location.search).get('p');
        const n = parseInt(p, 10);
        if (!isNaN(n) && n > 1) return `${base}_p${n}`;
    } catch (e) {}
    return base;
}

/**
 * Display a toast notification on the page.
 * @param {string} text - The text to display in the toast
 * @param {string} color - Background color (CSS color value)
 * @returns {void}
 */
function showToast(text, color) {
    const toast = document.createElement('div');
    toast.className = "jrpd-toast";
    toast.textContent = text;
    toast.style.position = "fixed";
    toast.style.top = "20%";
    toast.style.left = "50%";
    toast.style.transform = "translateX(-50%)";
    toast.style.background = color;
    toast.style.color = "#fff";
    toast.style.padding = "12px 30px";
    toast.style.borderRadius = "50px";
    toast.style.zIndex = "2147483647";
    toast.style.fontFamily = "sans-serif";
    toast.style.fontWeight = "bold";
    toast.style.pointerEvents = "none";
    toast.style.boxShadow = "0 4px 15px rgba(0,0,0,0.5)";
    toast.style.border = "1px solid rgba(255,255,255,0.2)";
    toast.style.transition = "opacity 0.5s ease";
    (typeof jrpdOverlayParent === "function" ? jrpdOverlayParent() : document.body).appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 500);
    }, 1500);
}

/**
 * Convert seconds to YouTube timestamp format (M:SS or H:MM:SS).
 * @param {number} seconds - Time in seconds
 * @returns {string} Formatted timestamp string
 */
function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}` : `${m}:${s.toString().padStart(2, '0')}`;
}

/**
 * Parse a timestamp string to seconds.
 * @param {string|number} ts - Timestamp string (M:SS or H:MM:SS) or seconds
 * @returns {number} Total seconds
 */
function parseTimestampToSeconds(ts) {
    if (typeof ts === 'number') return ts;
    if (!ts) return 0;
    return ts.split(':').reduce((acc, time) => (60 * acc) + Number(time), 0);
}

/**
 * Find the end of a gap between marks.
 * @param {string[]} marksArr - Array of timestamp strings
 * @param {number} startSec - Start position in seconds
 * @param {number} [videoDuration] - Total video duration in seconds
 * @returns {number} End position in seconds, or -1 if not found
 */
function getGapEndSeconds(marksArr, startSec, videoDuration) {
    const sortedMarks = (marksArr || [])
        .map(parseTimestampToSeconds)
        .filter((val) => !Number.isNaN(val))
        .sort((a, b) => a - b);
    for (const mark of sortedMarks) {
        if (mark > startSec) return mark;
    }
    return videoDuration || -1;
}

/**
 * Record a mark at the current video position.
 * Sends the mark to the backend server.
 * @returns {Promise<void>}
 */
async function doMark() {
    const now = Date.now();
    if (now - lastMarkTime < 3000) return;

    const hostname = window.location.hostname;
    // Get server base URL based on platform - make it global for jrpd_marker
    serverBaseUrl = (typeof jrpdGetServerBase === "function") ? jrpdGetServerBase() : getServerUrl();
    // Make available globally
    if (typeof window !== 'undefined') {
        window.serverBaseUrl = serverBaseUrl;
    }
    // Cross-platform video element detection
    let video;
    if (hostname.includes('youtube.com')) {
        video = document.querySelector('video.html5-main-video') || document.querySelector('video');
    } else if (hostname.includes('bilibili.com')) {
        video = document.querySelector('video.bilibili-player-video') ||
                document.querySelector('.bilibili-player-video-area video') ||
                document.querySelector('video');
    } else {
        video = document.querySelector('video');
    }
    if (!video) {
        console.log('JRPD: Video element not found');
        return;
    }
    
    // Cross-platform video ID extraction
    let videoId = 'default';
    if (hostname.includes('youtube.com')) {
        videoId = new URLSearchParams(window.location.search).get('v') || 'default';
    } else if (hostname.includes('bilibili.com')) {
        videoId = getBilibiliVideoKey();
    }
    vid = videoId;
    
    const reactionTime = 0.3;
    const finalTs = Math.floor(video.currentTime - (reactionTime * video.playbackRate));
    
    if (lastRecordedTs !== -1 && Math.abs(finalTs - lastRecordedTs) < 5) {
        console.log(`JRPD: Blocked proximity mark at ${finalTs} (too close to ${lastRecordedTs})`);
        return;
    }

    const displayTs = formatTime(finalTs);
    if (!marks.includes(finalTs)) {
        lastMarkTime = now;
        lastRecordedTs = finalTs;
        marks.push(finalTs);
        showToast(`${displayTs} Marked`, "#2e7d32");
        // Ensure live results panel is open and visible
        if (typeof openResultsPanel === "function" && typeof isResultsPanelVisible === "function" && !isResultsPanelVisible()) {
            openResultsPanel(false);
        }
        // Optimistically display the new mark immediately in the results panel
        if (typeof addOptimisticResultRow === "function") {
            addOptimisticResultRow(displayTs, "Processing...");
        } else if (typeof window !== "undefined" && typeof window.addOptimisticResultRow === "function") {
            window.addOptimisticResultRow(displayTs, "Processing...");
        }

        try {
            console.log(`JRPD: Sending mark ts=${finalTs} vid=${vid}`);
            jrpdFetch(`${serverBaseUrl}/add_mark?ts=${finalTs}&vid=${vid}`)
                .then(r => {
                    console.log('JRPD: Mark response', r.status);
                    refreshVisibleResultsPanel();
                })
                .catch(e => console.error('JRPD: Mark fetch error', e));
        } catch (e) {
            console.error('JRPD: Mark exception', e);
        }
        // Refresh the live results panel shortly after the server records the mark
        setTimeout(refreshVisibleResultsPanel, 300);
        setTimeout(refreshVisibleResultsPanel, 800);
    }
}

/**
 * Refresh the results panel if it is currently visible.
 * Safe to call before the panel modules are loaded.
 * @param {Object} [options] - Options for fetchResultsFile
 * @returns {void}
 */
function refreshVisibleResultsPanel(options = { forceFullRender: false }) {
    try {
        if (typeof isResultsPanelVisible === "function" && isResultsPanelVisible() && typeof fetchResultsFile === "function") {
            fetchResultsFile(options);
        }
    } catch (e) {
        console.warn("JRPD: refreshVisibleResultsPanel failed", e);
    }
}

/**
 * Undo the last recorded mark.
 * Removes the mark and seeks to that position.
 * @returns {Promise<void>}
 */
async function doUndo() {
    if (marks.length === 0) return;
    const removed = marks.pop();
    
    // Seek to the undone time
    const hostname = window.location.hostname;
    let video;
    if (hostname.includes('youtube.com')) {
        video = document.querySelector('video.html5-main-video') || document.querySelector('video');
    } else if (hostname.includes('bilibili.com')) {
        video = document.querySelector('video.bilibili-player-video') ||
                document.querySelector('.bilibili-player-video-area video') ||
                document.querySelector('video');
    } else {
        video = document.querySelector('video');
    }
    if (video) {
        video.currentTime = removed;
    }
    
    lastRecordedTs = marks.length > 0 ? marks[marks.length - 1] : -1;
    const displayTs = formatTime(removed);
    showToast(`${displayTs} Undone`, "#c62828");

    // Optimistically remove the undone mark from live results panel immediately
    if (typeof removeOptimisticResultRow === "function") {
        removeOptimisticResultRow(displayTs);
    } else if (typeof window !== "undefined" && typeof window.removeOptimisticResultRow === "function") {
        window.removeOptimisticResultRow(displayTs);
    }

    try {
        console.log(`JRPD: Sending UNDO for vid=${vid}`);
        jrpdFetch(`${serverBaseUrl}/add_mark?ts=[UNDO]&vid=${vid}`)
            .then(r => {
                console.log('JRPD: UNDO response', r.status);
                refreshVisibleResultsPanel();
            })
            .catch(e => console.error('JRPD: UNDO fetch error', e));
    } catch (e) {
        console.error('JRPD: UNDO exception', e);
    }

    setTimeout(refreshVisibleResultsPanel, 300);
    setTimeout(refreshVisibleResultsPanel, 800);
}

/**
 * Finish the marking session.
 * Notifies the backend server to finalize.
 * @returns {Promise<void>}
 */
async function doFinish() {
    // Cross-platform video ID extraction
    const hostname = window.location.hostname;
    let videoId = 'default';
    if (hostname.includes('youtube.com')) {
        videoId = new URLSearchParams(window.location.search).get('v') || 'default';
    } else if (hostname.includes('bilibili.com')) {
        videoId = (typeof getBilibiliVideoKey === "function") ? getBilibiliVideoKey() : 'default';
    }
    vid = videoId;
    showToast("Session Finished", "#6200ea");
    try {
        console.log(`JRPD: Sending FINISH for vid=${vid}`);
        const finishBase = (typeof serverBaseUrl !== "undefined" && serverBaseUrl) ? serverBaseUrl : getServerUrl();
        jrpdFetch(`${finishBase}/add_mark?ts=[FINISH]&vid=${vid}`)
            .then(r => console.log('JRPD: FINISH response', r.status))
            .catch(e => console.error('JRPD: FINISH fetch error', e));
    } catch (e) {
        console.error('JRPD: FINISH exception', e);
    }
}

/**
 * Fullscreen overlay support.
 * Browsers only render the fullscreen element's subtree, so page-level
 * overlays appended to document.body disappear in fullscreen. These helpers
 * re-parent JRPD overlays into the fullscreen element while it is active.
 */

/**
 * Get the active fullscreen element, if any.
 * @returns {Element|null} The fullscreen element or null
 */
function jrpdGetFullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
}

/**
 * Get the correct parent for page-level overlays.
 * @returns {Element} Fullscreen element when active, otherwise document.body
 */
function jrpdOverlayParent() {
    return jrpdGetFullscreenElement() || document.body;
}

/**
 * Remember the last fullscreen container so panels created *while*
 * fullscreen was active (and therefore never got the fs-moved flag)
 * can still be moved back to document.body on exit.
 */
var jrpdLastFsContainer = null;

/** Continuously-remembered scroll positions (backup if a read races layout). */
var jrpdPanelScrollMemory = {};

/**
 * Get the scrollable JRPD list elements that exist right now.
 * Main panel = jrpd-results-list; others kept in sync for consistency.
 * @returns {Element[]}
 */
function jrpdGetScrollablePanelLists() {
    var ids = ["jrpd-results-list", "jrpd-unified-list", "jrpd-candidate-list"];
    var out = [];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) out.push(el);
    });
    return out;
}

/**
 * Attach passive scroll listeners once per list so we always know the last
 * good position even if a capture reads 0 during a DOM move.
 * @returns {void}
 */
function jrpdTrackPanelScrollMemory() {
    try {
        jrpdGetScrollablePanelLists().forEach(function(el) {
            if (el.dataset.jrpdScrollTracked === "1") return;
            el.dataset.jrpdScrollTracked = "1";
            el.addEventListener("scroll", function() {
                try {
                    jrpdPanelScrollMemory[el.id] = {
                        top: el.scrollTop,
                        atBottom: (el.scrollHeight - el.scrollTop - el.clientHeight) < 60
                    };
                } catch (e) {}
            }, { passive: true });
        });
    } catch (e) {}
}

/**
 * Snapshot current scroll positions before a fullscreen reparent.
 * Falls back to remembered positions when the live read looks reset.
 * @returns {Object} Map of id -> {top, atBottom}
 */
function jrpdCapturePanelScroll() {
    jrpdTrackPanelScrollMemory();
    var state = {};
    try {
        jrpdGetScrollablePanelLists().forEach(function(el) {
            var top = el.scrollTop;
            var atBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 60;
            var mem = jrpdPanelScrollMemory[el.id];
            if (mem && top === 0 && mem.top > 0 && el.scrollHeight > el.clientHeight) {
                top = mem.top;
                atBottom = mem.atBottom;
            } else {
                jrpdPanelScrollMemory[el.id] = { top: top, atBottom: atBottom };
            }
            state[el.id] = { top: top, atBottom: atBottom };
        });
    } catch (e) {}
    return state;
}

/**
 * Restore scroll positions after a fullscreen reparent.
 * Applies immediately plus on later frames/timeouts so polling
 * re-renders or layout passes cannot leave the list pinned at top.
 * @param {Object} state - Map from jrpdCapturePanelScroll()
 * @returns {void}
 */
function jrpdRestorePanelScroll(state) {
    if (!state) return;
    function apply() {
        try {
            Object.keys(state).forEach(function(id) {
                var el = document.getElementById(id);
                if (!el) return;
                var s = state[id];
                if (!s) return;
                if (s.atBottom) el.scrollTop = el.scrollHeight;
                else el.scrollTop = s.top;
                jrpdPanelScrollMemory[id] = { top: el.scrollTop, atBottom: s.atBottom };
            });
        } catch (e) {}
    }
    apply();
    try {
        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(function() { apply(); });
            requestAnimationFrame(function() { setTimeout(apply, 60); });
        }
    } catch (e) {}
    setTimeout(apply, 60);
    setTimeout(apply, 300);
}

/**
 * Move JRPD overlays into/out of the fullscreen element so they stay visible.
 * Tracks moved nodes via data attribute so they can be restored to body on exit.
 * Scroll positions of the panel lists are preserved across both directions,
 * and panels created while fullscreen was active are moved back on exit.
 * @returns {void}
 */
function jrpdReparentOverlaysForFullscreen() {
    var scrollState = null;
    try { scrollState = jrpdCapturePanelScroll(); } catch (e) {}
    try {
        const fsEl = jrpdGetFullscreenElement();
        if (fsEl) {
            jrpdLastFsContainer = fsEl;
            document.querySelectorAll('body > [id^="jrpd-"], body > .jrpd-modal-overlay, body > .jrpd-toast').forEach(el => {
                if (el.parentElement === fsEl) return;
                el.dataset.jrpdFsMoved = "1";
                fsEl.appendChild(el);
            });
        } else {
            document.querySelectorAll('[data-jrpd-fs-moved="1"]').forEach(el => {
                delete el.dataset.jrpdFsMoved;
                if (el.parentElement !== document.body) document.body.appendChild(el);
            });
            // Panels created while fullscreen was active never got the flag and
            // would otherwise stay stuck inside the old fullscreen container.
            try {
                if (jrpdLastFsContainer) {
                    var stuck = [];
                    Array.prototype.forEach.call(jrpdLastFsContainer.children || [], function(el) {
                        if (!el) return;
                        var isBodyOverlay = false;
                        if (el.id === "jrpd-results-panel" || el.id === "jrpd-unified-panel" || el.id === "jrpd-cleanup-panel") {
                            isBodyOverlay = true;
                        } else if (el.classList && (el.classList.contains("jrpd-modal-overlay") || el.classList.contains("jrpd-toast"))) {
                            isBodyOverlay = true;
                        } else if (el.hasAttribute && el.hasAttribute("data-jrpd-fs-moved")) {
                            isBodyOverlay = true;
                        }
                        if (isBodyOverlay && el.parentElement !== document.body) stuck.push(el);
                    });
                    stuck.forEach(function(el) {
                        try { delete el.dataset.jrpdFsMoved; document.body.appendChild(el); } catch (e) {}
                    });
                    try {
                        if (!jrpdLastFsContainer.isConnected) jrpdLastFsContainer = null;
                    } catch (e) {}
                }
            } catch (e) {}
        }
    } catch (e) {
        console.warn("JRPD: overlay reparent failed", e);
    }
    try { jrpdRestorePanelScroll(scrollState); } catch (e) {}
}

(function jrpdInitFullscreenHook() {
    try {
        const root = document.documentElement;
        if (root && !root.hasAttribute("data-jrpd-fs-hook")) {
            root.setAttribute("data-jrpd-fs-hook", "1");
            document.addEventListener("fullscreenchange", jrpdReparentOverlaysForFullscreen);
            document.addEventListener("webkitfullscreenchange", jrpdReparentOverlaysForFullscreen);
        }
    } catch (e) {}
})();