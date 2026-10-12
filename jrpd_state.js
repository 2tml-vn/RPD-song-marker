// JRPD State Variables
// Shared state across all JRPD modules

// Central server host config (Fix 4: single source of truth).
// Override via localStorage 'jrpd-server-host' if your LAN IP changes.
var JRPD_LOCAL_HOST = 'http://127.0.0.1:5000';
var JRPD_BILIBILI_HOST = 'http://192.168.100.108:5000';

function jrpdGetServerBase() {
    try {
        const override = localStorage.getItem('jrpd-server-host');
        if (override) return override;
    } catch (e) {}
    const hostname = window.location.hostname;
    return hostname.includes('bilibili.com') ? JRPD_BILIBILI_HOST : JRPD_LOCAL_HOST;
}

let marks = [];
let vid = "";
let lastMarkTime = 0;
let lastRecordedTs = -1;
let lastSeekTs = -1;
let lastStatusMsg = "";
let currentCandidates = [];
let cleanupMarks = [];
let currentGapStart = -1;
let currentGapEnd = -1;
let isReviewMode = false;
let reviewLastMtime = 0;
let reviewLoopActive = false;
let reviewActiveGapTs = null;
let reviewSelectedTs = null;
let panelAutoOpened = false; // auto-opened the results panel for current video (once per video)
let songListsCache = null;
let songListsLoading = false;

// Previous results snapshot for identification detection (ts -> song text; null = not initialized yet)
let jrpdPrevResultsMap = null;

// Flagged timestamps for manual review (persisted in localStorage, session-to-session)
let flaggedTimestamps = new Set();