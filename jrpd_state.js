// JRPD State Variables
// Shared state across all JRPD modules

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
let songListsCache = null;
let songListsLoading = false;
let lastMarkedTimeDisplay = "--:--";

// Heart-marked timestamps for review (session-only)
let heartMarkedTimestamps = new Set();

// Time box drag state
let timeBoxDragActive = false;
let timeBoxDragOffset = { x: 0, y: 0 };