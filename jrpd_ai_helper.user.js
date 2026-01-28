// ==UserScript==
// @name         JRPD AI Helper
// @namespace    http://tampermonkey.net/
// @version      2.2
// @description  Visible & Robust AI Helper for JRPD Session.
// @author       Gemini CLI
// @match        *://*.youtube.com/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    if (window.self !== window.top) return;
    console.log("JRPD: AI Helper Script Started");

    let lastSuggestion = -1;

    function formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function showToast(text, color) {
        const toast = document.createElement('div');
        toast.textContent = text;
        toast.style.cssText = `
            position: fixed; top: 15%; left: 50%; transform: translateX(-50%);
            background: ${color}; color: white; padding: 12px 25px;
            border-radius: 50px; z-index: 2147483647; font-weight: bold;
            font-family: sans-serif; box-shadow: 0 8px 20px rgba(0,0,0,0.4);
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 1200);
    }

    function pulseButton(id) {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.style.transform = "scale(0.95)";
        btn.style.filter = "brightness(1.5)";
        setTimeout(() => { btn.style.transform = "scale(1)"; btn.style.filter = "none"; }, 100);
    }

    function initAIPanel() {
        if (document.getElementById("jrpd-ai-panel")) return;
        if (!document.body) return;

        console.log("JRPD: Injecting AI Panel...");
        const panel = document.createElement('div');
        panel.id = "jrpd-ai-panel";
        
        // Use cssText for absolute priority and reset
        panel.style.cssText = `
            all: initial;
            position: fixed !important;
            top: ${localStorage.getItem("jrpd-ai-top") || "100px"} !important;
            right: ${localStorage.getItem("jrpd-ai-right") || "20px"} !important;
            width: ${localStorage.getItem("jrpd-ai-width") || "180px"} !important;
            min-width: 160px !important;
            padding: 15px !important;
            border-radius: 16px !important;
            background: rgba(30, 30, 30, 0.98) !important;
            color: white !important;
            font-family: sans-serif !important;
            text-align: center !important;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8) !important;
            border: 2px solid #ff9800 !important;
            z-index: 2147483647 !important;
            display: block !important;
            cursor: default !important;
            user-select: none !important;
            overflow: hidden !important;
        `;

        const header = document.createElement('div');
        header.style.cssText = "display:flex; justify-content:space-between; margin-bottom:12px; font-size:11px; cursor:move; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:5px; color: white;";
        
        const titleSpan = document.createElement('span');
        const bTag = document.createElement('b');
        bTag.textContent = "AI"; bTag.style.color = "#ff9800";
        titleSpan.appendChild(bTag); titleSpan.appendChild(document.createTextNode(" HELPER"));
        
        const statusDot = document.createElement('span');
        statusDot.id = "ai-status-dot";
        statusDot.textContent = "● Offline";
        statusDot.style.color = "#ff4444";
        
        header.appendChild(titleSpan); header.appendChild(statusDot);
        panel.appendChild(header);

        function createBtn(id, text, color, onClick) {
            const btn = document.createElement('button');
            btn.id = id; btn.textContent = text;
            btn.style.cssText = `
                width: 100%; padding: 10px 5px; background: ${color};
                color: white; border: none; border-radius: 8px;
                cursor: pointer; font-size: 11px; font-weight: bold;
                margin-top: 8px; transition: transform 0.1s;
            `;
            btn.onclick = (e) => { e.stopPropagation(); onClick(); };
            return btn;
        }

        // --- Suggestion Box ---
        const aiBox = document.createElement('div');
        aiBox.id = "jrpd-suggestion-box";
        aiBox.style.cssText = "margin-bottom:15px; padding:12px; border-radius:10px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); color: white;";
        
        const aiLabel = document.createElement('div');
        aiLabel.id = "jrpd-ai-label"; aiLabel.textContent = "IDLE";
        aiLabel.style.cssText = "font-size:9px; font-weight:bold; color: white;";
        aiBox.appendChild(aiLabel);

        const aiTime = document.createElement('div');
        aiTime.id = "jrpd-ai-time"; aiTime.textContent = "--:--";
        aiTime.style.cssText = "font-size:24px; font-weight:bold; margin:5px 0; color: white;";
        aiBox.appendChild(aiTime);

        const aiBtns = document.createElement('div');
        aiBtns.id = "jrpd-ai-btns";
        aiBtns.style.cssText = "display:none; gap:8px;";

        const btnA = document.createElement('button');
        btnA.id = "jrpd-btn-a"; btnA.textContent = "YES (A)";
        btnA.style.cssText = "flex:1; padding:10px 5px; background:#2e7d32; color:white; border:none; border-radius:8px; cursor:pointer; font-size:11px; font-weight:bold;";
        btnA.onclick = (e) => { e.stopPropagation(); pulseButton("jrpd-btn-a"); sendEvaluation('a'); };
        
        const btnN = document.createElement('button');
        btnN.id = "jrpd-btn-n"; btnN.textContent = "NO (N)";
        btnN.style.cssText = "flex:1; padding:10px 5px; background:#c62828; color:white; border:none; border-radius:8px; cursor:pointer; font-size:11px; font-weight:bold;";
        btnN.onclick = (e) => { e.stopPropagation(); pulseButton("jrpd-btn-n"); sendEvaluation('n'); };

        aiBtns.appendChild(btnA); aiBtns.appendChild(btnN);
        aiBox.appendChild(aiBtns);
        panel.appendChild(aiBox);

        // --- Status Counter ---
        const statusArea = document.createElement('div');
        statusArea.style.cssText = "display:flex; justify-content:space-between; font-size:10px; margin-bottom:5px; opacity:0.7; color: white;";
        const verCount = document.createElement('span'); verCount.id = "jrpd-verified-count"; verCount.textContent = "Total: 0";
        const qCount = document.createElement('span'); qCount.id = "jrpd-queue-count"; qCount.textContent = "Queue: 0";
        statusArea.appendChild(verCount); statusArea.appendChild(qCount);
        panel.appendChild(statusArea);

        // --- Manual Controls ---
        panel.appendChild(createBtn("jrpd-btn-m", "MARK MISSING (M)", "#1976d2", () => { pulseButton("jrpd-btn-m"); doMark(); }));
        panel.appendChild(createBtn("jrpd-btn-u", "UNDO LAST (U)", "#616161", () => { pulseButton("jrpd-btn-u"); sendSignal('[UNDO]'); }));
        panel.appendChild(createBtn("jrpd-btn-f", "FINISH SESSION", "#6200ea", () => { pulseButton("jrpd-btn-f"); sendSignal('[FINISH]'); }));
        
        document.body.appendChild(panel);

        // Drag Logic
        let isDragging = false, ox, oy;
        header.onmousedown = (e) => { isDragging = true; ox = e.clientX - panel.offsetLeft; oy = e.clientY - panel.offsetTop; };
        document.addEventListener('mousemove', (e) => {
            if (isDragging) { 
                panel.style.left = (e.clientX - ox) + 'px'; 
                panel.style.top = (e.clientY - oy) + 'px'; 
                panel.style.right = 'auto'; 
            }
        });
        document.addEventListener('mouseup', () => {
            if (isDragging) { 
                localStorage.setItem("jrpd-ai-top", panel.style.top); 
                localStorage.setItem("jrpd-ai-left", panel.style.left);
                localStorage.setItem("jrpd-ai-right", panel.style.right);
            }
            isDragging = false;
        });
    }

    async function sendEvaluation(choice) {
        try {
            await fetch(`http://localhost:5000/evaluate?choice=${choice}`);
            showToast(choice === 'a' ? "[A] Accepted" : "[N] Rejected", choice === 'a' ? "#2e7d32" : "#c62828");
        } catch (e) {}
    }

    async function doMark() {
        const video = document.querySelector('video');
        if (!video) return;
        const ts = Math.floor(video.currentTime);
        try {
            await fetch(`http://localhost:5000/add_mark?ts=${ts}`);
            showToast(`[M] Marked ${formatTime(ts)}`, "#1976d2");
        } catch (e) {}
    }

    async function sendSignal(signal) {
        try {
            await fetch(`http://localhost:5000/add_mark?ts=${signal}`);
            showToast(signal === '[UNDO]' ? "[U] Undone" : "Finished", "#6200ea");
        } catch (e) {}
    }

    // Sync Loop
    setInterval(async () => {
        const statusDot = document.getElementById("ai-status-dot");
        const box = document.getElementById("jrpd-suggestion-box");
        const label = document.getElementById("jrpd-ai-label");
        const aiTime = document.getElementById("jrpd-ai-time");
        const aiBtns = document.getElementById("jrpd-ai-btns");
        const verCount = document.getElementById("jrpd-verified-count");
        const qCount = document.getElementById("jrpd-queue-count");
        const video = document.querySelector('video');

        try {
            const response = await fetch('http://localhost:5000/get_suggestion');
            const data = await response.json();
            if (statusDot) { statusDot.textContent = "● Online"; statusDot.style.color = "#4CAF50"; }
            if (verCount) verCount.textContent = `Total: ${data.verified}`;
            if (qCount) qCount.textContent = `Queue: ${data.queue}`;

            if (data.sec > 0) {
                if (box) { box.style.background = "rgba(255, 152, 0, 0.15)"; box.style.border = "1px solid rgba(255, 152, 0, 0.4)"; }
                if (label) { label.textContent = "NEXT START?"; label.style.color = "#ff9800"; }
                if (aiTime) aiTime.textContent = formatTime(data.sec);
                if (aiBtns) aiBtns.style.display = "flex";
                if (data.sec !== lastSuggestion && video) {
                    lastSuggestion = data.sec;
                    video.currentTime = Math.max(0, data.sec - 1.0);
                }
            } else {
                if (box) { box.style.background = "rgba(255, 255, 255, 0.05)"; box.style.border = "1px solid rgba(255, 255, 255, 0.1)"; }
                if (label) { label.textContent = "IDLE"; label.style.color = "white"; }
                if (aiTime) aiTime.textContent = "--:--";
                if (aiBtns) aiBtns.style.display = "none";
            }
        } catch (e) {
            if (statusDot) { statusDot.textContent = "● Offline"; statusDot.style.color = "#ff4444"; }
        }
    }, 1000);

    document.addEventListener('keydown', (e) => {
        const box = document.getElementById("jrpd-ai-btns");
        const isInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable;
        if (isInput) return;
        const suggesting = box && box.style.display === "flex";
        const k = e.key.toLowerCase();
        if (k === 'a' && suggesting) { e.preventDefault(); pulseButton("jrpd-btn-a"); sendEvaluation('a'); }
        else if (k === 'n' && suggesting) { e.preventDefault(); pulseButton("jrpd-btn-n"); sendEvaluation('n'); }
        else if (k === 'm') { e.preventDefault(); pulseButton("jrpd-btn-m"); doMark(); }
        else if (k === 'u') { e.preventDefault(); pulseButton("jrpd-btn-u"); sendSignal('[UNDO]'); }
    });

    setInterval(initAIPanel, 1000);
})();
