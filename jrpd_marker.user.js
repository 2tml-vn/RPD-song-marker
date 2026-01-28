// ==UserScript==
// @name         JRPD Live Marker Pro
// @namespace    http://tampermonkey.net/
// @version      6.0
// @description  Bar-only UI: Undo/Finish in YT bar. 'A' to mark.
// @author       Gemini CLI
// @match        *://*.youtube.com/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    let marks = [];
    let vid = "";
    let lastMarkTime = 0;
    let lastRecordedTs = -1;

    function showToast(text, color) {
        const toast = document.createElement('div');
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
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            setTimeout(() => toast.remove(), 500);
        }, 1500);
    }

    function formatTime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}` : `${m}:${s.toString().padStart(2, '0')}`;
    }

    async function doMark() {
        const now = Date.now();
        if (now - lastMarkTime < 3000) return; // 3 second hardware cooldown

        const video = document.querySelector('video');
        if (!video) return;
        vid = new URLSearchParams(window.location.search).get('v') || 'default';
        
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
            try { fetch(`http://localhost:5000/add_mark?ts=${finalTs}&vid=${vid}`); } catch (e) {}
        }
    }

    async function doUndo() {
        if (marks.length === 0) return;
        const removed = marks.pop();
        lastRecordedTs = marks.length > 0 ? marks[marks.length - 1] : -1;
        const displayTs = formatTime(removed);
        showToast(`${displayTs} Undone`, "#c62828");
        try { fetch(`http://localhost:5000/add_mark?ts=[UNDO]&vid=${vid}`); } catch (e) {}
    }

    async function doFinish() {
        vid = new URLSearchParams(window.location.search).get('v') || 'default';
        showToast("Session Finished", "#6200ea");
        try { fetch(`http://localhost:5000/add_mark?ts=[FINISH]&vid=${vid}`); } catch (e) {}
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

    const checkInterval = setInterval(() => {
        const currentVid = new URLSearchParams(window.location.search).get('v');
        
        if (currentVid && currentVid !== vid) {
            vid = currentVid;
            marks = [];
            lastRecordedTs = -1;
        }

        if (window.location.href.includes("watch") && document.querySelector('video') && document.body) {
            injectControls();
        }
    }, 500);
})();
