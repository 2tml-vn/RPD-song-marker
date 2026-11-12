// ==UserScript==
// @name         JRPD Live Marker Pro
// @version      8.11
// @description  Modular userscript for marking songs in YouTube and Bilibili videos
// @author       Gemini CLI
// @match        *://*.youtube.com/*
// @match        *://*.bilibili.com/*
// @require      file:///D:/rpd/jrpd_state.js
// @require      file:///D:/rpd/jrpd_utils.js
// @require      file:///D:/rpd/jrpd_cleanup.js
// @require      file:///D:/rpd/jrpd_results.js
// @require      file:///D:/rpd/jrpd_songs.js
// @grant        GM_xmlhttpRequest
// @grant        GM_log
// @grant        unsafeWindow
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    // Platform detection
    function getPlatform() {
        const hostname = window.location.hostname;
        if (hostname.includes('youtube.com')) return 'youtube';
        if (hostname.includes('bilibili.com')) return 'bilibili';
        return null;
    }

    // Get server base URL based on platform
    function getServerBaseUrl() {
        if (typeof jrpdGetServerBase === 'function') return jrpdGetServerBase();
        const platform = getPlatform();
        if (platform === 'bilibili') {
            // Bilibili blocks loopback, use LAN IP instead
            if (typeof JRPD_BILIBILI_HOST !== 'undefined') return JRPD_BILIBILI_HOST;
            return 'http://192.168.100.108:5000';
        }
        // YouTube works fine with 127.0.0.1
        if (typeof JRPD_LOCAL_HOST !== 'undefined') return JRPD_LOCAL_HOST;
        return 'http://127.0.0.1:5000';
    }

    // Cross-platform fetch that uses GM_xmlhttpRequest when available to bypass CORS & loopback restrictions
    function jrpdFetch(url, options = {}) {
        if (typeof GM_xmlhttpRequest !== 'undefined') {
            return new Promise((resolve, reject) => {
                GM_xmlhttpRequest({
                    method: options.method || 'GET',
                    url: url,
                    headers: options.headers || {},
                    data: options.body || null,
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
        }
        return fetch(url, options);
    }

    // Helper to get video ID from URL (cross-platform)
    // Bilibili multi-part: ?p=N (N>1) becomes "BVxxx_pN" so parts get separate sessions.
    // ?p=1 or missing p keeps the bare "BVxxx" key for backward compat.
    function getVideoId() {
        const platform = getPlatform();
        if (!platform) return null;

        if (typeof getBilibiliVideoKey === 'function' && platform === 'bilibili') {
            return getBilibiliVideoKey();
        }
        
        if (platform === 'youtube') {
            return new URLSearchParams(window.location.search).get('v');
        } else if (platform === 'bilibili') {
            const path = window.location.pathname;
            const match = path.match(/\/video\/(BV[0-9A-Za-z]+|av\d+|\d+)/);
            if (!match) return null;
            const base = match[1];
            try {
                const n = parseInt(new URLSearchParams(window.location.search).get('p'), 10);
                if (!isNaN(n) && n > 1) return `${base}_p${n}`;
            } catch (e) {}
            return base;
        }
        return null;
    }

    // Helper to check if we're on a video watch page
    function isVideoPage() {
        const platform = getPlatform();
        const videoId = getVideoId();
        if (!platform || !videoId) return false;
        
        if (platform === 'youtube') {
            return window.location.href.includes("watch");
        } else if (platform === 'bilibili') {
            return window.location.pathname.includes('/video/');
        }
        return false;
    }

    // Helper to get video player container
    function getVideoContainer() {
        const platform = getPlatform();
        if (platform === 'youtube') {
            return document.querySelector('.html5-video-player') || document.querySelector('#movie_player');
        } else if (platform === 'bilibili') {
            return document.querySelector('#bilibili-player') ||
                   document.querySelector('.bilibili-player') ||
                   document.querySelector('.bilibili-player-video-area') ||
                   document.querySelector('.bilibili-player-video');
        }
        return null;
    }


    function getVideoElement() {
        const platform = getPlatform();
        if (platform === 'youtube') {
            return document.querySelector('video.html5-main-video') || document.querySelector('video');
        } else if (platform === 'bilibili') {
            return document.querySelector('video.bilibili-player-video') ||
                   document.querySelector('.bilibili-player-video-area video') ||
                   document.querySelector('video');
        }
        return null;
    }

    function getControlBar() {
        const platform = getPlatform();
        if (platform === 'youtube') {
            return document.querySelector('.ytp-left-controls');
        } else if (platform === 'bilibili') {
            // Try shadow DOM access
            const playerEl = document.querySelector('bilibili-player') || document.querySelector('[data-component="video-player"]');
            if (playerEl?.shadowRoot) {
                const controlBar = playerEl.shadowRoot.querySelector('.bpx-player-control-bottom') ||
                                  playerEl.shadowRoot.querySelector('.bpx-player-control-bar');
                if (controlBar) return controlBar;
            }
            
            // Fallback to regular selectors
            return document.querySelector('#bilibili-player > div > div > div.bpx-player-primary-area > div.bpx-player-video-area > div.bpx-player-control-wrap > div.bpx-player-control-entity') ||
                   document.querySelector('.bpx-player-control-bottom') ||
                   document.querySelector('.bilibili-player-video-controls') ||
                   document.querySelector('.bilibili-player-bottom-area') ||
                   document.querySelector('[data-ui="control-bar"]');
        }
        return null;
    }

    // Function to inject buttons into control bar
    function injectButtonsToControlBar(controlBar, platform) {
        function createBarBtn(id, text, color, onClick) {
            const btn = document.createElement("button");
            btn.id = id;
            btn.className = "ytp-button";
            btn.style.width = "auto";
            btn.style.padding = "0 10px";
            btn.style.fontSize = "12px";
            btn.style.fontWeight = "bold";
            btn.style.color = color;
            btn.textContent = text;
            btn.onclick = (e) => {
                e.preventDefault();
                onClick();
            };
            return btn;
        }

        function ensureBarBtn(id, text, color, onClick) {
            return document.getElementById(id) || createBarBtn(id, text, color, onClick);
        }
        
        const undoBtn = ensureBarBtn("jrpd-undo-btn", "UNDO", "#ff4444", doUndo);
        const finishBtn = ensureBarBtn("jrpd-finish-btn", "FINISH", "#6200ea", doFinish);
        const panelBtn = ensureBarBtn("jrpd-panel-toggle-btn", "📋", "#eeeeee", toggleResultsPanel);

        // Seat buttons in the CURRENT control bar. appendChild/insertBefore move
        // an existing node (preserving handlers), which covers fullscreen mode
        // when the player swaps in a different bar element.
        if (platform === 'bilibili') {
            if (undoBtn.parentElement !== controlBar) controlBar.appendChild(undoBtn);
            if (finishBtn.parentElement !== controlBar) controlBar.appendChild(finishBtn);
            if (panelBtn.parentElement !== controlBar) controlBar.appendChild(panelBtn);
        } else {
            const timeDisplay = controlBar.querySelector(".ytp-time-display");
            if (timeDisplay) {
                const slot = timeDisplay.parentNode;
                if (finishBtn.parentElement !== slot) slot.insertBefore(finishBtn, timeDisplay.nextSibling);
                if (undoBtn.parentElement !== slot) slot.insertBefore(undoBtn, finishBtn.nextSibling);
                if (panelBtn.parentElement !== slot) slot.insertBefore(panelBtn, undoBtn.nextSibling);
            } else {
                if (undoBtn.parentElement !== controlBar) controlBar.appendChild(undoBtn);
                if (finishBtn.parentElement !== controlBar) controlBar.appendChild(finishBtn);
                if (panelBtn.parentElement !== controlBar) controlBar.appendChild(panelBtn);
            }
        }
        if (typeof updatePanelToggleButton === "function") updatePanelToggleButton();
    }
    
    let jrpdControlObserver = null;
    let jrpdControlBarCache = null;
    function injectControls() {
        const platform = getPlatform();
        const controlBar = getControlBar();
        if (controlBar) {
            if (jrpdControlObserver) { jrpdControlObserver.disconnect(); jrpdControlObserver = null; }
            // Poll runs every second: only re-seat when the bar element changed
            // (fullscreen/SPA swaps) or the buttons went missing (player rebuilt
            // its subtree). Skipping avoids the deep selector queries and DOM
            // appends every tick during normal playback.
            if (jrpdControlBarCache === controlBar && document.getElementById("jrpd-undo-btn")) return;
            jrpdControlBarCache = controlBar;
            injectButtonsToControlBar(controlBar, platform);
            return;
        }
        jrpdControlBarCache = null;
        
        // Control bar not ready yet (Bilibili loads it dynamically): watch once.
        if (platform === 'bilibili' && !jrpdControlObserver && document.body) {
            // Watch only the player subtree. An observer on document.body fires
            // for every unrelated mutation on busy pages (danmaku, comments,
            // progress UI) and each callback costs several querySelectors.
            const watchRoot = document.querySelector('#bilibili-player') ||
                              document.querySelector('.bilibili-player') ||
                              document.body;
            jrpdControlObserver = new MutationObserver(() => {
                const bar = getControlBar();
                if (bar) {
                    if (jrpdControlObserver) { jrpdControlObserver.disconnect(); jrpdControlObserver = null; }
                    jrpdControlBarCache = bar;
                    injectButtonsToControlBar(bar, platform);
                }
            });
            jrpdControlObserver.observe(watchRoot, { childList: true, subtree: true });
            // Timeout after 10 seconds
            setTimeout(() => { if (jrpdControlObserver) { jrpdControlObserver.disconnect(); jrpdControlObserver = null; } }, 10000);
        }
    }

    // Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.repeat) return;
        const activeEl = document.activeElement;
        const isInput = activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable;
        if (isInput) return;

        if (e.key.toLowerCase() === 'a') {
            doMark();
        }
    });



    // Keep control-bar buttons visible in fullscreen: the player may swap in a
    // different control-bar element, so buttons are re-seated on change.
    function jrpdHandleFullscreenChange() {
        try {
            const bar = getControlBar();
            if (bar) {
                jrpdControlBarCache = bar;
                injectButtonsToControlBar(bar, getPlatform());
            }
        } catch (e) {}
    }
    document.addEventListener("fullscreenchange", jrpdHandleFullscreenChange);
    document.addEventListener("webkitfullscreenchange", jrpdHandleFullscreenChange);


    // Main polling loop
    const checkInterval = setInterval(() => {
        const currentVid = getVideoId();
        
        if (currentVid && currentVid !== vid) {
            vid = currentVid;
            marks = [];
            lastRecordedTs = -1;
            panelAutoOpened = false;
            reviewLastMtime = 0;
            try { if (typeof jrpdResetIdentDetection === "function") jrpdResetIdentDetection(); } catch (e) {}
            if (typeof fetchResultsFile === "function") {
                fetchResultsFile({ forceFullRender: true });
            }
        }

        if (isVideoPage() && document.querySelector('video') && document.body) {
            injectControls();
            createCleanupPanel();
            createResultsPanel();
            
            
            // Poll server status
            jrpdFetch(getServerBaseUrl() + "/status")
                .then(r => r.json())
                .then(data => {
                    // Start button follows the live connection state
                    if (typeof updateStartBtn === "function") updateStartBtn(true);

                    // Review Mode Detection
                    if (data.is_review_mode && !isReviewMode) {
                        isReviewMode = true;
                        const cleanupPanel = document.getElementById("jrpd-cleanup-panel");
                        if (cleanupPanel) cleanupPanel.style.display = "none";
                        openResultsPanel();
                        console.log("JRPD: Entered Review Mode");
                    }

                    // Live panel refresh: keep results panel updated in real time during marking and review
                    if (typeof isResultsPanelVisible === "function" && isResultsPanelVisible()) {
                        fetchResultsFile();
                    }

                    // Seek-loop for the active panel gap (works while marking too).
                    // Never loop an ended video: it must stay ended.
                    const loopVideo = getVideoElement();
                    if (loopVideo && reviewLoopActive && !loopVideo.ended && currentGapStart >= 0 && currentGapEnd > currentGapStart && loopVideo.currentTime >= currentGapEnd) {
                        console.log(`JRPD: Looping gap ${currentGapStart} -> ${currentGapEnd}`);
                        loopVideo.currentTime = currentGapStart;
                    }

                    // Review mode does not run the remote-seek / cleanup flow
                    if (isReviewMode) return;

                    // Remote Seek
                    if (data.seek_ts !== undefined && data.seek_ts !== -1 && data.seek_ts !== lastSeekTs) {
                        const video = getVideoElement();
                        if (video) {
                            console.log(`JRPD: Remote Seek Request for ${data.seek_ts}`);
                            video.currentTime = data.seek_ts;
                            setTimeout(() => { 
                                if (Math.abs(video.currentTime - data.seek_ts) > 1) video.currentTime = data.seek_ts;
                            }, 100);
                            lastSeekTs = data.seek_ts;
                            currentGapStart = data.seek_ts;
                            currentGapEnd = getGapEndSeconds(cleanupMarks, currentGapStart, video.duration);
                            showToast(`Seeking to ${formatTime(data.seek_ts)}`, "#f57c00");

                            const list = document.getElementById("jrpd-candidate-list");
                            if (list) list.style.opacity = "1.0";
                        }
                    }

                    // Candidates UI
                    if (JSON.stringify(data.candidates) !== JSON.stringify(currentCandidates)) {
                        currentCandidates = data.candidates || [];
                        updateCandidates(currentCandidates);
                    }

                    // Status Messages
                    if (data.status_msg && data.status_msg !== lastStatusMsg) {
                        showToast(data.status_msg, "#0288d1");
                        lastStatusMsg = data.status_msg;
                    }

                    // Update cleanup marks (never override a panel-selected loop gap)
                    if (data.marks) {
                        cleanupMarks = data.marks || [];
                        const video2 = getVideoElement();
                        if (video2 && currentGapStart !== -1 && reviewActiveGapTs === null) {
                            currentGapEnd = getGapEndSeconds(cleanupMarks, currentGapStart, video2.duration);
                        }
                    }

                    // Cleanup gap loop. Never loop an ended video: it must stay ended.
                    const video = getVideoElement();
                    if (video && !video.ended && currentCandidates.length > 0 && currentGapStart >= 0 && currentGapEnd > currentGapStart && video.currentTime >= currentGapEnd) {
                        console.log(`JRPD: Looping gap ${currentGapStart} -> ${currentGapEnd}`);
                        video.currentTime = currentGapStart;
                    }
                })
                .catch(e => {
                    if (typeof updateStartBtn === "function") updateStartBtn(false);
                    if (currentCandidates.length > 0) {
                        console.error("JRPD: Server disconnected during cleanup.");
                        currentCandidates = [];
                        updateCandidates([]);
                    }
                });
        }
    }, 1000);

})();