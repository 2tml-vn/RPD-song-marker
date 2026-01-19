// ==UserScript==
// @name         JRPD Live Marker Pro
// @namespace    http://tampermonkey.net/
// @version      5.1
// @description  Trusted Types Safe + Toast Notifications + Adaptive Dimming.
// @author       Gemini CLI
// @match        *://*.youtube.com/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    let marks = [];
    let isLocked = false;
    let vid = "";

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

    function initUI() {
        if (document.getElementById("jrpd-marker-container")) return;
        if (!document.body) return;

        const container = document.createElement('div');
        container.id = "jrpd-marker-container";
        container.style.setProperty("position", "fixed", "important");
        
        const savedTop = localStorage.getItem("jrpd-pos-top");
        const savedLeft = localStorage.getItem("jrpd-pos-left");

        if (savedTop === "auto" && savedLeft === "auto") {
            // Restore Docked State
            container.style.setProperty("top", "auto", "important");
            container.style.setProperty("bottom", "20px", "important");
            container.style.setProperty("left", "auto", "important");
            container.style.setProperty("right", "20px", "important");
        } else {
            // Restore Free-floating State
            container.style.setProperty("top", savedTop || "100px", "important");
            container.style.setProperty("left", savedLeft || "20px", "important");
            container.style.setProperty("bottom", "auto", "important");
            container.style.setProperty("right", "auto", "important");
        }

        container.style.setProperty("z-index", "2147483647", "important");
        container.style.width = "200px";
        container.style.minWidth = "160px";
        container.style.padding = "15px";
        container.style.borderRadius = "16px";
        container.style.textAlign = "center";
        container.style.userSelect = "none";
        container.style.fontFamily = "'Roboto', sans-serif";
        container.style.border = "1px solid rgba(255,255,255,0.1)";
        container.style.boxShadow = "0 8px 32px 0 rgba(0,0,0,0.8)";
        container.style.resize = "both";
        container.style.overflow = "hidden";
        container.style.background = "rgba(10, 10, 10, 0.4)";
        container.style.backdropFilter = "blur(12px) brightness(0.6)";
        container.style.webkitBackdropFilter = "blur(12px) brightness(0.6)";
        container.style.transition = "border-color 0.3s ease, box-shadow 0.3s ease, opacity 0.6s ease";
        container.style.opacity = "0.2";

        const title = document.createElement('div');
        title.id = "jrpd-handle";
        title.style.marginBottom = "10px";
        title.style.fontSize = "11px";
        title.style.cursor = "move";
        title.style.padding = "5px";
        title.style.borderBottom = "1px solid rgba(255,255,255,0.1)";
        title.style.display = "flex";
        title.style.justifyContent = "space-between";
        title.style.alignItems = "center";
        
        const dragLabel = document.createElement('span');
        const b = document.createElement('b');
        b.textContent = "JRPD";
        b.style.color = "#ff4444";
        dragLabel.appendChild(b);
        dragLabel.appendChild(document.createTextNode(" PRO"));
        title.appendChild(dragLabel);

        const controls = document.createElement('div');
        controls.style.display = "flex";
        controls.style.gap = "8px";

        const minBtn = document.createElement('span');
        minBtn.textContent = localStorage.getItem("jrpd-minimized") === "true" ? "+" : "−";
        minBtn.style.cursor = "pointer";
        minBtn.style.fontSize = "14px";
        minBtn.style.fontWeight = "bold";
        minBtn.style.lineHeight = "1";
        
        if (localStorage.getItem("jrpd-minimized") === "true") {
            container.style.height = "30px";
            title.style.borderBottom = "none";
        }

        minBtn.onclick = (e) => {
            e.stopPropagation();
            const isMinimized = container.style.height === "30px";
            container.style.height = isMinimized ? "auto" : "30px";
            minBtn.textContent = isMinimized ? "−" : "+";
            title.style.borderBottom = isMinimized ? "1px solid rgba(255,255,255,0.1)" : "none";
            localStorage.setItem("jrpd-minimized", !isMinimized);
        };
        controls.appendChild(minBtn);

        const dockBtn = document.createElement('span');
        dockBtn.textContent = "⚓";
        dockBtn.style.cursor = "pointer";
        dockBtn.style.fontSize = "12px";
        dockBtn.style.opacity = "0.7";
        dockBtn.title = "Dock to Corner";
        dockBtn.onclick = (e) => {
            e.stopPropagation();
            doDock();
        };
        controls.appendChild(dockBtn);

        const lockBtn = document.createElement('span');
        lockBtn.textContent = "👁️";
        lockBtn.style.cursor = "pointer";
        lockBtn.style.opacity = "0.5";
        lockBtn.style.fontSize = "12px";
        lockBtn.onclick = (e) => {
            e.stopPropagation();
            isLocked = !isLocked;
            lockBtn.style.opacity = isLocked ? "1" : "0.5";
            container.style.opacity = isLocked ? "1" : "0.2";
        };
        controls.appendChild(lockBtn);
        title.appendChild(controls);
        container.appendChild(title);

        const recentBox = document.createElement('div');
        recentBox.style.background = "rgba(0,0,0,0.2)";
        recentBox.style.padding = "8px";
        recentBox.style.borderRadius = "8px";
        recentBox.style.marginBottom = "12px";
        recentBox.style.border = "1px solid rgba(255,255,255,0.05)";
        recentBox.style.transition = "transform 0.2s ease";
        
        const recentTime = document.createElement('div');
        recentTime.id = "jrpd-recent-time";
        recentTime.textContent = "--:--";
        recentTime.style.fontSize = "24px";
        recentTime.style.fontWeight = "bold";
        recentTime.style.color = "#40c4ff";
        recentTime.style.fontFamily = "monospace";
        recentTime.style.transition = "color 0.3s ease";
        recentBox.appendChild(recentTime);
        container.appendChild(recentBox);

        const counter = document.createElement('div');
        counter.id = "jrpd-counter";
        counter.textContent = "Marks: 0";
        counter.style.fontSize = "11px";
        counter.style.fontWeight = "bold";
        counter.style.marginBottom = "12px";
        counter.style.color = "#4CAF50";
        counter.style.opacity = "0.8";
        container.appendChild(counter);

        function createBtn(text, color, onClick) {
            const btn = document.createElement('button');
            btn.textContent = text;
            btn.style.width = "100%";
            btn.style.marginBottom = "8px";
            btn.style.padding = "10px";
            btn.style.background = color;
            btn.style.color = "white";
            btn.style.border = "none";
            btn.style.borderRadius = "8px";
            btn.style.cursor = "pointer";
            btn.style.fontWeight = "bold";
            btn.style.fontSize = "11px";
            btn.style.opacity = "0.8";
            btn.onclick = (e) => { e.stopPropagation(); onClick(); };
            return btn;
        }

        container.appendChild(createBtn("MARK", "#2e7d32", () => doMark()));
        container.appendChild(createBtn("UNDO", "#c62828", () => doUndo()));
        container.appendChild(createBtn("FINISH", "#6200ea", () => doFinish()));
        document.body.appendChild(container);

        // Sub-Logic
        function doDock() {
            isLocked = false;
            container.style.opacity = "1";
            container.style.setProperty("height", "30px", "important");
            container.style.setProperty("top", "auto", "important");
            container.style.setProperty("bottom", "20px", "important");
            container.style.setProperty("left", "auto", "important");
            container.style.setProperty("right", "20px", "important");
            minBtn.textContent = "+";
            title.style.borderBottom = "none";
            localStorage.setItem("jrpd-minimized", "true");
            localStorage.setItem("jrpd-pos-top", "auto");
            localStorage.setItem("jrpd-pos-left", "auto");
        }

        function triggerPulse(color) {
            container.style.borderColor = color;
            container.style.boxShadow = `0 0 15px ${color}`;
            recentBox.style.transform = "scale(1.05)";
            setTimeout(() => {
                container.style.borderColor = "rgba(255,255,255,0.1)";
                container.style.boxShadow = "0 8px 32px 0 rgba(0,0,0,0.8)";
                recentBox.style.transform = "scale(1.0)";
            }, 400);
        }

        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}` : `${m}:${s.toString().padStart(2, '0')}`;
        }

        async function doMark() {
            const video = document.querySelector('video');
            if (!video) return;
            vid = new URLSearchParams(window.location.search).get('v') || 'default';
            // Adjust offset based on playback speed (reaction time compensation)
            const reactionTime = 0.3;
            const finalTs = Math.floor(video.currentTime - (reactionTime * video.playbackRate));
            const displayTs = formatTime(finalTs);
            if (!marks.includes(finalTs)) {
                marks.push(finalTs);
                document.getElementById("jrpd-counter").textContent = `Marks: ${marks.length}`;
                document.getElementById("jrpd-recent-time").textContent = displayTs;
                triggerPulse("#4CAF50");
                showToast(`${displayTs} Marked`, "#2e7d32");
                try { fetch(`http://localhost:5000/add_mark?ts=${finalTs}&vid=${vid}`); } catch (e) {}
            }
        }

        async function doUndo() {
            if (marks.length === 0) return;
            const removed = marks.pop();
            const displayTs = formatTime(removed);
            document.getElementById("jrpd-counter").textContent = `Marks: ${marks.length}`;
            document.getElementById("jrpd-recent-time").textContent = marks.length > 0 ? formatTime(marks[marks.length-1]) : "--:--";
            triggerPulse("#ff4444");
            showToast(`${displayTs} Undone`, "#c62828");
            try { fetch(`http://localhost:5000/add_mark?ts=[UNDO]&vid=${vid}`); } catch (e) {}
        }

        async function doFinish() {
            vid = new URLSearchParams(window.location.search).get('v') || 'default';
            triggerPulse("#6200ea");
            showToast("Session Finished", "#6200ea");
            
            // Auto-collapse and move to corner
            isLocked = false;
            container.style.opacity = "1";
            container.style.setProperty("height", "30px", "important");
            container.style.setProperty("top", "auto", "important");
            container.style.setProperty("bottom", "20px", "important");
            container.style.setProperty("left", "auto", "important");
            container.style.setProperty("right", "20px", "important");
            minBtn.textContent = "+";
            title.style.borderBottom = "none";
            localStorage.setItem("jrpd-minimized", "true");
            localStorage.setItem("jrpd-pos-top", "auto");
            localStorage.setItem("jrpd-pos-left", "auto");

            try { fetch(`http://localhost:5000/add_mark?ts=[FINISH]&vid=${vid}`); } catch (e) {}
        }

        // Keyboard Shortcuts
        document.addEventListener('keydown', (e) => {
            const activeEl = document.activeElement;
            const isInput = activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable;
            if (isInput) return;

            if (e.key.toLowerCase() === 'a') {
                doMark();
            }
        });

        // Drag Logic
        let isDragging = false, offsetX, offsetY;
        title.onmousedown = (e) => { isDragging = true; offsetX = e.clientX - container.offsetLeft; offsetY = e.clientY - container.offsetTop; };
        document.onmousemove = (e) => { if (isDragging) { container.style.left = (e.clientX - offsetX) + 'px'; container.style.top = (e.clientY - offsetY) + 'px'; container.style.right = 'auto'; } };
        document.onmouseup = () => {
            if (isDragging) {
                localStorage.setItem("jrpd-pos-top", container.style.top);
                localStorage.setItem("jrpd-pos-left", container.style.left);
            }
            isDragging = false;
        };

        // Enforce Minimized State at the end to override any layout shifts
        if (localStorage.getItem("jrpd-minimized") === "true") {
            container.style.height = "30px";
            title.style.borderBottom = "none";
            minBtn.textContent = "+";
        }
    }

    const checkInterval = setInterval(() => {
        const currentVid = new URLSearchParams(window.location.search).get('v');
        
        // Detect video change to reset session
        if (currentVid && currentVid !== vid) {
            vid = currentVid;
            marks = [];
            const container = document.getElementById("jrpd-marker-container");
            if (container) container.remove();
        }

        if (window.location.href.includes("watch") && document.querySelector('video') && document.body) {
            initUI();
        }
    }, 500);
})();