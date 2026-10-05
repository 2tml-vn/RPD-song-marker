/**
 * JRPD Utility Functions
 * Shared utilities for all JRPD modules
 * @module jrpd_utils
 */

/**
 * Display a toast notification on the page.
 * @param {string} text - The text to display in the toast
 * @param {string} color - Background color (CSS color value)
 * @returns {void}
 */
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
        lastMarkedTimeDisplay = displayTs;
        showToast(`${displayTs} Marked`, "#2e7d32");
        try { fetch(`http://127.0.0.1:5000/add_mark?ts=${finalTs}&vid=${vid}`); } catch (e) {}
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
    const video = document.querySelector('video');
    if (video) {
        video.currentTime = removed;
    }
    
    lastRecordedTs = marks.length > 0 ? marks[marks.length - 1] : -1;
    lastMarkedTimeDisplay = marks.length > 0 ? formatTime(marks[marks.length - 1]) : "--:--";
    const displayTs = formatTime(removed);
    showToast(`${displayTs} Undone`, "#c62828");
    try { fetch(`http://127.0.0.1:5000/add_mark?ts=[UNDO]&vid=${vid}`); } catch (e) {}
}

/**
 * Finish the marking session.
 * Notifies the backend server to finalize.
 * @returns {Promise<void>}
 */
async function doFinish() {
    vid = new URLSearchParams(window.location.search).get('v') || 'default';
    showToast("Session Finished", "#6200ea");
    try { fetch(`http://127.0.0.1:5000/add_mark?ts=[FINISH]&vid=${vid}`); } catch (e) {}
}