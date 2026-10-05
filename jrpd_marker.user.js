// ==UserScript==
// @name         JRPD Live Marker Pro
// @version      8.4
// @description  Modular userscript for marking songs in YouTube videos
// @author       Gemini CLI
// @match        *://*.youtube.com/*
// @require      file:///D:/rpd/jrpd_state.js
// @require      file:///D:/rpd/jrpd_utils.js
// @require      file:///D:/rpd/jrpd_cleanup.js
// @require      file:///D:/rpd/jrpd_results.js
// @require      file:///D:/rpd/jrpd_songs.js
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    // Helper to check if we're on a video watch page
    function isVideoPage() {
        return window.location.href.includes("watch") && new URLSearchParams(window.location.search).get('v');
    }

    // Helper to get video player container
    function getVideoContainer() {
        return document.querySelector('.html5-video-player') || document.querySelector('#movie_player');
    }

    // Helper to get saved time box position (video-relative)
    function getTimeBoxPosition() {
        const saved = localStorage.getItem('jrpd-timebox-video-position');
        if (saved) {
            try {
                return JSON.parse(saved);
            } catch (e) {
                return { left: 10, bottom: 10 };
            }
        }
        return { left: 10, bottom: 10 };
    }

    // Helper to save time box position (video-relative)
    function saveTimeBoxPosition(left, bottom) {
        localStorage.setItem('jrpd-timebox-video-position', JSON.stringify({ left, bottom }));
    }

    function injectControls() {
        if (document.getElementById("jrpd-undo-btn")) return;
        
        const controlBar = document.querySelector(".ytp-left-controls");
        if (!controlBar) return;

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

        const undoBtn = createBarBtn("jrpd-undo-btn", "UNDO", "#ff4444", doUndo);
        const finishBtn = createBarBtn("jrpd-finish-btn", "FINISH", "#6200ea", doFinish);

        const timeDisplay = controlBar.querySelector(".ytp-time-display");
        if (timeDisplay) {
            timeDisplay.parentNode.insertBefore(finishBtn, timeDisplay.nextSibling);
            timeDisplay.parentNode.insertBefore(undoBtn, finishBtn);
        } else {
            controlBar.appendChild(undoBtn);
            controlBar.appendChild(finishBtn);
        }
        console.log("JRPD: Bar Controls Injected");
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

    // Hover Time Popup - Invisible by default, box itself is hover zone, draggable
    function createHoverTimePopup() {
        if (document.getElementById("jrpd-time-popup")) return;

        const videoContainer = getVideoContainer();
        if (!videoContainer) return;

        const savedPos = getTimeBoxPosition();
        
        const popup = document.createElement("div");
        popup.id = "jrpd-time-popup";
        
        popup.style.cssText = `
            position: absolute;
            left: ${savedPos.left}px;
            bottom: ${savedPos.bottom}px;
            background: rgba(0,0,0,0.85);
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 14px;
            z-index: 9998;
            cursor: move;
            user-select: none;
            white-space: nowrap;
            display: block;
            opacity: 0;
            transition: opacity 0.3s ease;
            border: 1px solid rgba(255,255,255,0.2);
        `;
        
        videoContainer.appendChild(popup);

        // Hover to show
        popup.addEventListener("mouseenter", () => {
            if (!timeBoxDragActive) {
                popup.style.opacity = "1";
                updateHoverTimePopup();
            }
        });
        
        popup.addEventListener("mouseleave", () => {
            if (!timeBoxDragActive) {
                popup.style.opacity = "0";
            }
        });

        // Drag functionality
        popup.addEventListener('mousedown', (e) => {
            timeBoxDragActive = true;
            const rect = popup.getBoundingClientRect();
            timeBoxDragOffset = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };
            popup.style.transition = 'none';
            popup.style.opacity = "1";
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!timeBoxDragActive) return;
            
            const popup = document.getElementById("jrpd-time-popup");
            if (!popup) return;

            const container = popup.parentElement;
            if (!container) return;

            const containerRect = container.getBoundingClientRect();
            
            // Calculate position relative to container
            let newLeft = e.clientX - containerRect.left - timeBoxDragOffset.x;
            let newBottom = containerRect.bottom - e.clientY - timeBoxDragOffset.y;

            // Constrain to video container bounds
            const maxX = containerRect.width - popup.offsetWidth;
            const maxY = containerRect.height - popup.offsetHeight;
            
            newLeft = Math.max(0, Math.min(newLeft, maxX));
            newBottom = Math.max(0, Math.min(newBottom, maxY));

            popup.style.left = newLeft + 'px';
            popup.style.bottom = newBottom + 'px';
            popup.style.top = 'auto';
            popup.style.right = 'auto';
        });

        document.addEventListener('mouseup', () => {
            if (!timeBoxDragActive) return;
            timeBoxDragActive = false;
            
            const popup = document.getElementById("jrpd-time-popup");
            if (!popup) return;

            popup.style.transition = '';
            
            // Save position (as left/bottom relative to container)
            const left = parseFloat(popup.style.left) || 0;
            const bottom = parseFloat(popup.style.bottom) || 0;
            saveTimeBoxPosition(left, bottom);
        });

        // ResizeObserver to keep time box within video bounds when video resizes
        const resizeObserver = new ResizeObserver(() => {
            const popup = document.getElementById("jrpd-time-popup");
            if (!popup) return;

            const container = popup.parentElement;
            if (!container) return;

            const containerRect = container.getBoundingClientRect();
            const popupRect = popup.getBoundingClientRect();
            
            // Adjust if outside bounds
            const currentLeft = parseFloat(popup.style.left) || 0;
            const currentBottom = parseFloat(popup.style.bottom) || 0;
            
            let newLeft = currentLeft;
            let newBottom = currentBottom;
            
            if (currentLeft + popupRect.width > containerRect.width) {
                newLeft = Math.max(0, containerRect.width - popupRect.width - 10);
            }
            if (currentBottom + popupRect.height > containerRect.height) {
                newBottom = Math.max(0, containerRect.height - popupRect.height - 10);
            }
            
            if (newLeft !== currentLeft || newBottom !== currentBottom) {
                popup.style.left = newLeft + 'px';
                popup.style.bottom = newBottom + 'px';
            }
        });
        resizeObserver.observe(videoContainer);

        // Show/hide based on video page
        updateTimePopupVisibility();
    }

    function updateTimePopupVisibility() {
        const popup = document.getElementById("jrpd-time-popup");
        if (!popup) return;

        if (isVideoPage()) {
            // Ensure popup is in the video container (handles YouTube SPA navigation)
            const videoContainer = getVideoContainer();
            if (videoContainer && popup.parentElement !== videoContainer) {
                const savedPos = getTimeBoxPosition();
                popup.style.left = savedPos.left + 'px';
                popup.style.bottom = savedPos.bottom + 'px';
                videoContainer.appendChild(popup);
            }
            popup.style.display = 'block';
        } else {
            popup.style.display = 'none';
        }
    }

    function updateHoverTimePopup() {
        const popup = document.getElementById("jrpd-time-popup");
        if (!popup || popup.style.display === 'none') return;
        
        const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
        const currentTime = video ? formatTime(video.currentTime) : "--:--";
        
        popup.textContent = `${lastMarkedTimeDisplay} / ${currentTime}`;
    }

    // Handle YouTube SPA navigation
    function setupNavigationListener() {
        // Listen for YouTube's custom navigation events
        document.addEventListener('yt-navigate-finish', () => {
            updateTimePopupVisibility();
        });
        
        // Also check on history changes (pushState/popstate)
        let lastUrl = window.location.href;
        const urlCheckInterval = setInterval(() => {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                updateTimePopupVisibility();
            }
        }, 500);
    }

    // Main polling loop
    const checkInterval = setInterval(() => {
        const currentVid = new URLSearchParams(window.location.search).get('v');
        
        if (currentVid && currentVid !== vid) {
            vid = currentVid;
            marks = [];
            lastRecordedTs = -1;
        }

        if (isVideoPage() && document.querySelector('video') && document.body) {
            injectControls();
            createCleanupPanel();
            createResultsPanel();
            createHoverTimePopup();
            
            // Update hover popup time if visible
            const popup = document.getElementById("jrpd-time-popup");
            if (popup && popup.style.opacity === "1") {
                updateHoverTimePopup();
            }
            
            // Poll server status
            fetch("http://127.0.0.1:5000/status")
                .then(r => r.json())
                .then(data => {
                    // Review Mode Detection
                    if (data.is_review_mode && !isReviewMode) {
                        isReviewMode = true;
                        const cleanupPanel = document.getElementById("jrpd-cleanup-panel");
                        if (cleanupPanel) cleanupPanel.style.display = "none";
                        const resultsPanel = document.getElementById("jrpd-results-panel");
                        if (resultsPanel) resultsPanel.style.display = "flex";
                        fetchResultsFile();
                        console.log("JRPD: Entered Review Mode");
                    }

                    // Review Mode: poll results & handle loop
                    if (isReviewMode) {
                        fetchResultsFile();

                        const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
                        if (video && reviewLoopActive && currentGapStart >= 0 && currentGapEnd > currentGapStart && video.currentTime >= currentGapEnd) {
                            console.log(`JRPD: Review looping gap ${currentGapStart} -> ${currentGapEnd}`);
                            video.currentTime = currentGapStart;
                        }
                        return;
                    }

                    // Remote Seek
                    if (data.seek_ts !== undefined && data.seek_ts !== -1 && data.seek_ts !== lastSeekTs) {
                        const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
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

                    // Update cleanup marks
                    if (data.marks) {
                        cleanupMarks = data.marks || [];
                        const video2 = document.querySelector('video.html5-main-video') || document.querySelector('video');
                        if (video2 && currentGapStart !== -1) {
                            currentGapEnd = getGapEndSeconds(cleanupMarks, currentGapStart, video2.duration);
                        }
                    }

                    // Cleanup gap loop
                    const video = document.querySelector('video.html5-main-video') || document.querySelector('video');
                    if (video && currentCandidates.length > 0 && currentGapStart >= 0 && currentGapEnd > currentGapStart && video.currentTime >= currentGapEnd) {
                        console.log(`JRPD: Looping gap ${currentGapStart} -> ${currentGapEnd}`);
                        video.currentTime = currentGapStart;
                    }
                })
                .catch(e => {
                    if (currentCandidates.length > 0) {
                        console.error("JRPD: Server disconnected during cleanup.");
                        currentCandidates = [];
                        updateCandidates([]);
                    }
                });
        }
    }, 1000);

    // Setup navigation listener on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupNavigationListener);
    } else {
        setupNavigationListener();
    }
})();