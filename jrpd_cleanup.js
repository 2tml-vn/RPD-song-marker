// JRPD Cleanup Panel
// Handles cleanup mode UI and candidate selection

let fullCandidates = [];

function createCleanupPanel() {
    if (document.getElementById("jrpd-cleanup-panel")) return;
    const panel = document.createElement("div");
    panel.id = "jrpd-cleanup-panel";
    panel.style.cssText = "position: fixed; top: 100px; right: 20px; width: 300px; max-height: 80vh; background: #212121; color: white; z-index: 9999; padding: 15px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); display: none; flex-direction: column; font-family: Roboto, Arial, sans-serif; border: 1px solid #444;";
    
    // Header
    const header = document.createElement("div");
    header.style.cssText = "font-weight: bold; margin-bottom: 10px; border-bottom: 1px solid #444; padding-bottom: 5px; display: flex; justify-content: space-between;";
    const title = document.createElement("span");
    title.textContent = "Cleanup: Select Song";
    header.appendChild(title);
    panel.appendChild(header);

    // Search Input
    const searchInput = document.createElement("input");
    searchInput.id = "jrpd-cleanup-search";
    searchInput.type = "text";
    searchInput.placeholder = "Search...";
    searchInput.style.cssText = "width: 100%; box-sizing: border-box; padding: 6px 8px; margin-bottom: 8px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; font-size: 12px;";
    searchInput.addEventListener("input", () => {
        filterCleanupCandidates(searchInput.value);
    });
    panel.appendChild(searchInput);

    // List Container
    const list = document.createElement("div");
    list.id = "jrpd-candidate-list";
    list.style.cssText = "overflow-y: auto; flex-grow: 1; margin-bottom: 10px;";
    panel.appendChild(list);

    // Manual Entry - 4 structured input boxes
    const manualEntryDiv = document.createElement("div");
    manualEntryDiv.style.cssText = "margin-bottom: 10px; display: flex; flex-direction: column; gap: 4px;";
    const fieldDefs = [
        {id: "jrpd-add-key", placeholder: "Song Name (required)", field: "key"},
        {id: "jrpd-add-intl", placeholder: "Intl Name", field: "intl"},
        {id: "jrpd-add-artist", placeholder: "Artist", field: "artist_orig"},
        {id: "jrpd-add-artist-intl", placeholder: "Intl Artist", field: "artist_intl"},
    ];
    const inputStyle = "width: 100%; box-sizing: border-box; padding: 4px 6px; background: #333; color: white; border: 1px solid #444; border-radius: 4px; font-size: 11px;";
    fieldDefs.forEach(def => {
        const input = document.createElement("input");
        input.id = def.id;
        input.placeholder = def.placeholder;
        input.style.cssText = inputStyle;
        manualEntryDiv.appendChild(input);
    });
    const addBtn = document.createElement("button");
    addBtn.textContent = "Add Song";
    addBtn.style.cssText = "width: 100%; padding: 6px; background: #2e7d32; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; margin-top: 2px;";
    addBtn.onclick = () => {
        const key = document.getElementById("jrpd-add-key").value.trim();
        if (!key) return;
        const payload = {key};
        const intl = document.getElementById("jrpd-add-intl").value.trim();
        const artist = document.getElementById("jrpd-add-artist").value.trim();
        const artistIntl = document.getElementById("jrpd-add-artist-intl").value.trim();
        if (intl) payload.intl = intl;
        if (artist) payload.artist_orig = artist;
        if (artistIntl) payload.artist_intl = artistIntl;
        sendChoice("+" + JSON.stringify(payload));
        fieldDefs.forEach(def => { document.getElementById(def.id).value = ""; });
    };
    manualEntryDiv.appendChild(addBtn);
    panel.appendChild(manualEntryDiv);

    // Buttons
    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display: flex; gap: 5px;";
    
    const skipBtn = document.createElement("button");
    skipBtn.id = "jrpd-skip-btn";
    skipBtn.textContent = "Skip Gap";
    skipBtn.style.cssText = "flex: 1; padding: 8px; background: #444; color: white; border: none; border-radius: 4px; cursor: pointer;";
    skipBtn.onclick = () => sendChoice("s");
    
    const quitBtn = document.createElement("button");
    quitBtn.id = "jrpd-quit-btn";
    quitBtn.textContent = "Quit Cleanup";
    quitBtn.style.cssText = "flex: 1; padding: 8px; background: #c62828; color: white; border: none; border-radius: 4px; cursor: pointer;";
    quitBtn.onclick = () => sendChoice("q");

    btnRow.appendChild(skipBtn);
    btnRow.appendChild(quitBtn);
    panel.appendChild(btnRow);

    document.body.appendChild(panel);
}

function sendChoice(choice) {
    // Provide immediate visual feedback that a choice was made
    const list = document.getElementById("jrpd-candidate-list");
    if (list) list.style.opacity = "0.3";
    
    const encodedChoice = encodeURIComponent(choice);
    fetch(`http://127.0.0.1:5000/select?choice=${encodedChoice}`)
        .then(() => {
            if (choice === "q") {
                document.getElementById("jrpd-cleanup-panel").style.display = "none";
            }
        })
        .catch(e => {
            console.error("JRPD: Choice failed", e);
            if (list) list.style.opacity = "1.0";
        });
}

function filterCleanupCandidates(searchText) {
    const list = document.getElementById("jrpd-candidate-list");
    if (!list) return;
    
    const search = (searchText || "").toLowerCase();
    const filtered = fullCandidates.filter(cand => cand.toLowerCase().includes(search));
    
    list.textContent = "";
    list.style.opacity = "1.0";
    
    filtered.forEach((cand) => {
        const originalIndex = fullCandidates.indexOf(cand);
        const btn = document.createElement("div");
        btn.textContent = cand;
        btn.style.cssText = "padding: 8px; margin-bottom: 5px; background: #333; cursor: pointer; border-radius: 4px; font-size: 13px; transition: background 0.2s;";
        btn.onmouseover = () => btn.style.background = "#444";
        btn.onmouseout = () => btn.style.background = "#333";
        btn.onclick = () => sendChoice(originalIndex);
        list.appendChild(btn);
    });
}

function updateCandidates(candidates) {
    const panel = document.getElementById("jrpd-cleanup-panel");
    if (!panel) return;
    
    if (!candidates || candidates.length === 0) {
        panel.style.display = "none";
        currentGapStart = -1;
        currentGapEnd = -1;
        fullCandidates = [];
        return;
    }

    // Store full list for filtering
    fullCandidates = [...candidates];

    panel.style.display = "flex";
    const list = document.getElementById("jrpd-candidate-list");
    const searchInput = document.getElementById("jrpd-cleanup-search");
    
    // Clear search input and add-song input fields
    if (searchInput) searchInput.value = "";
    ["jrpd-add-key","jrpd-add-intl","jrpd-add-artist","jrpd-add-artist-intl"].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = "";
    });
    
    // Render full list
    filterCleanupCandidates("");
}