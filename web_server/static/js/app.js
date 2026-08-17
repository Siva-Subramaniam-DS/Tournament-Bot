/* =========================================================================
   TOURNAMENT WEB PORTAL CLIENT JAVASCRIPT & BRACKET CREATOR STUDIO
   ========================================================================= */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Login Tabs if on Login Page
    initLoginTabs();

    // 2. Initialize Dashboard Tabs if on Dashboard Page
    initDashboardTabs();

    // 3. Initialize Forms
    initMasterLoginForm();
    initSponsorForm();
    initAffiliateForm();
    initCreateUserForm();

    // 4. Initialize Bracket Creator Studio (Organizer Dashboard)
    initBracketCreatorStudio();

    // 5. Initialize Public Tournament Live Bracket Viewer (/tournament/<id>)
    initPublicTournamentBracketViewer();

    // 6. Initialize Server Configuration & Web Command Console
    initServerConfigAndCommandConsole();

    // 7. Initialize Tournament Table Actions (Edit & Delete)
    initTournamentTableActions();
});

// =========================================================================
// TAB SWITCHER HELPERS
// =========================================================================
function switchDashboardTab(targetPanelId) {
    const dashBtns = document.querySelectorAll(".dash-tab-btn");
    const dashPanels = document.querySelectorAll(".dash-panel");

    dashBtns.forEach(b => {
        if (b.getAttribute("data-panel") === targetPanelId) {
            b.classList.add("active");
        } else {
            b.classList.remove("active");
        }
    });

    dashPanels.forEach(p => {
        if (p.id === targetPanelId) {
            p.style.display = "block";
        } else {
            p.style.display = "none";
        }
    });
}

function initLoginTabs() {
    const tabBtns = document.querySelectorAll(".login-tab-btn");
    const tabPanels = document.querySelectorAll(".login-tab-panel");
    if (tabBtns.length === 0) return;

    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            tabBtns.forEach(b => b.classList.remove("active"));
            tabPanels.forEach(p => p.style.display = "none");

            btn.classList.add("active");
            const targetId = btn.getAttribute("data-tab");
            const targetPanel = document.getElementById(targetId);
            if (targetPanel) {
                targetPanel.style.display = "block";
            }
        });
    });
}

function initDashboardTabs() {
    const dashBtns = document.querySelectorAll(".dash-tab-btn");
    const dashPanels = document.querySelectorAll(".dash-panel");
    if (dashBtns.length === 0) return;

    dashBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            dashBtns.forEach(b => b.classList.remove("active"));
            dashPanels.forEach(p => p.style.display = "none");

            btn.classList.add("active");
            const targetId = btn.getAttribute("data-panel");
            const targetPanel = document.getElementById(targetId);
            if (targetPanel) {
                targetPanel.style.display = "block";
            }
        });
    });
}

// =========================================================================
// MASTER LOGIN FORM AJAX
// =========================================================================
function initMasterLoginForm() {
    const form = document.getElementById("masterLoginForm");
    const errorBox = document.getElementById("loginErrorBox");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (errorBox) errorBox.style.display = "none";

        const usernameInput = document.getElementById("masterUsername");
        const passwordInput = document.getElementById("masterPassword");

        try {
            const res = await fetch("/api/auth/master-login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    username: usernameInput.value.trim(),
                    password: passwordInput.value
                })
            });

            const data = await res.json();
            if (res.ok && data.status === "success") {
                window.location.href = "/dashboard";
            } else {
                if (errorBox) {
                    errorBox.textContent = data.error || data.detail || "Invalid admin credentials.";
                    errorBox.style.display = "block";
                }
            }
        } catch (err) {
            if (errorBox) {
                errorBox.textContent = "Network error. Could not connect to server.";
                errorBox.style.display = "block";
            }
        }
    });
}

// =========================================================================
// INTERACTIVE ANIMATED BRACKET CREATOR STUDIO
// =========================================================================
function initBracketCreatorStudio() {
    const studioContainer = document.getElementById("bracket-studio-panel");
    if (!studioContainer) return;

    // Team Seed Data State (Starts empty - no preloaded dummy data)
    let currentTeams = [];

    const teamTagsContainer = document.getElementById("studioTeamTagsContainer");
    const newTeamInput = document.getElementById("studioNewTeamInput");
    const addTeamBtn = document.getElementById("studioAddTeamBtn");
    const teamCountLabel = document.getElementById("studioTeamCount");
    const bracketVisualContainer = document.getElementById("bracketVisualContainer");
    const generateBtn = document.getElementById("studioGenerateBracketBtn");
    const publishBtn = document.getElementById("studioPublishBtn");
    const feedbackBox = document.getElementById("studioFeedback");

    // Game Category selector buttons
    const gameButtons = document.querySelectorAll(".game-select-btn");
    const gameHiddenInput = document.getElementById("studioGameCategory");
    const customGameContainer = document.getElementById("customGameInputContainer");
    const customGameInput = document.getElementById("studioCustomGameName");

    gameButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            gameButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const gameVal = btn.getAttribute("data-game");
            
            if (gameVal === "custom") {
                if (customGameContainer) customGameContainer.style.display = "block";
                if (gameHiddenInput && customGameInput) gameHiddenInput.value = customGameInput.value.trim() || "Custom Game";
            } else {
                if (customGameContainer) customGameContainer.style.display = "none";
                if (gameHiddenInput) gameHiddenInput.value = gameVal;
            }
        });
    });

    if (customGameInput && gameHiddenInput) {
        customGameInput.addEventListener("input", () => {
            gameHiddenInput.value = customGameInput.value.trim() || "Custom Game";
        });
    }

    // Helper to parse, clean and deduplicate team names from CSV or TXT
    function parseTeamsFromText(text) {
        if (!text) return [];
        const lines = text.split(/\r?\n/);
        const parsed = [];
        const seen = new Set();

        const headerKeywords = [
            "team name", "team names", "team", "teams", "team_name", "teamnames",
            "team-name", "name", "names", "player", "players", "player name",
            "participant", "participants", "roster", "club", "club name", "squad",
            "entry", "entries", "no", "no.", "sr no", "sr. no.", "#", "seed", "rank", "title"
        ];

        for (let i = 0; i < lines.length; i++) {
            let rawLine = lines[i].trim();
            if (rawLine.charCodeAt(0) === 0xFEFF) {
                rawLine = rawLine.substring(1).trim();
            }
            if (!rawLine) continue;

            let candidate = rawLine;
            if (candidate.includes(",") || candidate.includes("\t") || candidate.includes(";")) {
                const parts = candidate.split(/[,;\t]/).map(p => p.trim().replace(/^["']|["']$/g, '').trim()).filter(Boolean);
                if (parts.length > 0) {
                    if (parts.length > 1 && (/^#?\d+$/.test(parts[0]) || parts[0].toLowerCase() === "no." || parts[0] === "#")) {
                        candidate = parts[1];
                    } else {
                        candidate = parts[0];
                    }
                }
            }

            candidate = candidate.replace(/^["']|["']$/g, '').trim();
            candidate = candidate.replace(/^team\s*name\s*:\s*/i, '')
                                 .replace(/^team\s*:\s*/i, '')
                                 .replace(/^#\s*\d+\s*[-.:]?\s*/i, '');

            if (!candidate) continue;

            const normalized = candidate.toLowerCase().replace(/[:#._-]/g, '').trim();
            if (headerKeywords.includes(normalized) || headerKeywords.includes(candidate.toLowerCase().trim())) {
                continue;
            }

            const lowerKey = candidate.toLowerCase();
            if (!seen.has(lowerKey) && parsed.length < 256) {
                seen.add(lowerKey);
                parsed.push(candidate);
            }
        }

        return parsed;
    }

    // CSV / TXT File Upload Handler (Up to 256 teams)
    const csvFileInput = document.getElementById("csvFileInput");
    if (csvFileInput) {
        csvFileInput.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (event) => {
                const text = event.target.result;
                const parsed = parseTeamsFromText(text);
                if (parsed.length > 0) {
                    currentTeams = parsed;
                    document.querySelectorAll(".btn-chip").forEach(b => {
                        if (b.id && b.id.startsWith("studioQuick")) b.classList.remove("active");
                    });
                    renderTeamPills();
                    generateAnimatedBracket();
                    if (feedbackBox) {
                        feedbackBox.style.color = "#34d399";
                        feedbackBox.textContent = `📂 Successfully imported ${parsed.length} teams (no duplicates) from ${file.name}!`;
                    }
                } else {
                    if (feedbackBox) {
                        feedbackBox.style.color = "#ef4444";
                        feedbackBox.textContent = `❌ No valid team names found in ${file.name}`;
                    }
                }
                csvFileInput.value = "";
            };
            reader.readAsText(file);
        });
    }

    // Render team pills
    function renderTeamPills() {
        if (!teamTagsContainer) return;
        teamTagsContainer.innerHTML = "";

        if (currentTeams.length === 0) {
            teamTagsContainer.innerHTML = `
                <div style="color: var(--text-muted); font-size: 0.8rem; padding: 12px 8px; text-align: center; width: 100%;">
                    No teams added yet. Type a team name above, upload CSV/TXT, or click a preset to begin.
                </div>
            `;
            if (teamCountLabel) teamCountLabel.textContent = "0 / 256 Teams";
            return;
        }

        currentTeams.forEach((team, idx) => {
            const pill = document.createElement("div");
            pill.className = "team-tag-pill";
            pill.innerHTML = `
                <span style="color: var(--primary-cyan); font-size: 0.7rem;">#${idx + 1}</span>
                <span>${team}</span>
                <span class="team-tag-remove" data-index="${idx}">&times;</span>
            `;
            teamTagsContainer.appendChild(pill);
        });

        if (teamCountLabel) teamCountLabel.textContent = `${currentTeams.length} / 256 Teams`;

        // Bind delete events
        teamTagsContainer.querySelectorAll(".team-tag-remove").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const idx = parseInt(e.target.getAttribute("data-index"));
                currentTeams.splice(idx, 1);
                renderTeamPills();
                generateAnimatedBracket();
            });
        });
    }

    renderTeamPills();

    // Add Team Button
    if (addTeamBtn && newTeamInput) {
        const handleAdd = () => {
            const val = newTeamInput.value.trim();
            if (val) {
                if (currentTeams.length >= 256) {
                    if (feedbackBox) {
                        feedbackBox.style.color = "#ef4444";
                        feedbackBox.textContent = "⚠️ Maximum limit of 256 teams reached.";
                    }
                    return;
                }
                currentTeams.push(val);
                newTeamInput.value = "";
                renderTeamPills();
                generateAnimatedBracket();
            }
        };
        addTeamBtn.addEventListener("click", handleAdd);
        newTeamInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                handleAdd();
            }
        });
    }

    // Helper to generate realistic team rosters up to 256 teams
    function generateSampleTeams(count) {
        const topTeams = [
            "Sentinels", "Paper Rex", "Fnatic", "Team Heretics",
            "LOUD", "NRG Esports", "Team Liquid", "DRX",
            "Cloud9", "T1 Esports", "Gen.G", "Karmine Corp",
            "Leviatan", "NAVI", "Team Secret", "ZETA DIVISION",
            "G2 Esports", "FaZe Clan", "OpTic Gaming", "100 Thieves",
            "Team Vitality", "Furia Esports", "Astralis", "MOUZ",
            "Ninjas in Pyjamas", "Heroic", "Team SoloMid", "Complexity",
            "BIG Clan", "ENCE", "Virtus.pro", "Team Falcons",
            "Team Spirit", "FlyQuest", "Bilibili Gaming", "Edward Gaming",
            "JD Gaming", "Top Esports", "Weibo Gaming", "FunPlus Phoenix",
            "Invictus Gaming", "Royal Never Give Up", "Dplus KIA", "Hanwha Life",
            "KT Rolster", "Kwangdong Freecs", "DRX Challengers", "T1 Academy",
            "Sentinels Youth", "LOUD Academy", "Karmine Blue", "KOI Esports",
            "GIANTX", "Team BDS", "MAD Lions", "Rogue",
            "Spacestation Gaming", "DarkZero", "Shopify Rebellion", "Moist Esports",
            "Oxygen Esports", "Version1", "Pittsburgh Knights", "Ghost Gaming"
        ];
        const res = [];
        for (let i = 0; i < count; i++) {
            if (i < topTeams.length) {
                res.push(topTeams[i]);
            } else {
                const num = i + 1;
                const suffixes = ["Esports", "Gaming", "Squad", "Legion", "Force", "Syndicate", "Vanguard", "Titans", "Elite", "Prime"];
                res.push(`Team ${num} ${suffixes[i % suffixes.length]}`);
            }
        }
        return res;
    }

    function setPreset(btn, count) {
        document.querySelectorAll(".btn-chip").forEach(b => {
            if (b.id && b.id.startsWith("studioQuick")) b.classList.remove("active");
        });
        if (btn) btn.classList.add("active");
        currentTeams = generateSampleTeams(count);
        renderTeamPills();
        generateAnimatedBracket();
    }

    const presetConfigs = [
        { id: "studioQuick4Btn", count: 4 },
        { id: "studioQuick8Btn", count: 8 },
        { id: "studioQuick16Btn", count: 16 },
        { id: "studioQuick32Btn", count: 32 },
        { id: "studioQuick64Btn", count: 64 },
        { id: "studioQuick128Btn", count: 128 },
        { id: "studioQuick256Btn", count: 256 }
    ];

    presetConfigs.forEach(p => {
        const btn = document.getElementById(p.id);
        if (btn) {
            btn.addEventListener("click", () => setPreset(btn, p.count));
        }
    });

    // Shuffle Button
    const shuffleBtn = document.getElementById("studioShuffleBtn");
    if (shuffleBtn) {
        shuffleBtn.addEventListener("click", () => {
            if (currentTeams.length < 2) return;
            for (let i = currentTeams.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [currentTeams[i], currentTeams[j]] = [currentTeams[j], currentTeams[i]];
            }
            renderTeamPills();
            generateAnimatedBracket();
        });
    }

    // Clear All Button
    const clearTeamsBtn = document.getElementById("studioClearTeamsBtn");
    if (clearTeamsBtn) {
        clearTeamsBtn.addEventListener("click", () => {
            currentTeams = [];
            document.querySelectorAll(".btn-chip").forEach(b => {
                if (b.id && b.id.startsWith("studioQuick")) b.classList.remove("active");
            });
            renderTeamPills();
            generateAnimatedBracket();
            if (feedbackBox) {
                feedbackBox.style.color = "#34d399";
                feedbackBox.textContent = "🧹 Cleared all teams.";
                setTimeout(() => feedbackBox.textContent = "", 2000);
            }
        });
    }

    // Dynamic Tournament Generation (Single Elimination & Group Stage A-Z)
    const bracketTypeSelect = document.getElementById("studioBracketType");
    const groupSettingsBox = document.getElementById("studioGroupSettingsBox");
    const groupCountSelect = document.getElementById("studioGroupCount");
    const groupAdvanceSelect = document.getElementById("studioGroupAdvanceCount");

    if (bracketTypeSelect) {
        bracketTypeSelect.addEventListener("change", () => {
            const val = bracketTypeSelect.value;
            if (groupSettingsBox) {
                groupSettingsBox.style.display = (val === "group_stage") ? "block" : "none";
            }
            generateAnimatedBracket();
        });
    }

    if (groupCountSelect) {
        groupCountSelect.addEventListener("change", generateAnimatedBracket);
    }
    if (groupAdvanceSelect) {
        groupAdvanceSelect.addEventListener("change", generateAnimatedBracket);
    }

    function generateAnimatedBracket() {
        if (!bracketVisualContainer) return;
        bracketVisualContainer.innerHTML = "";

        const numTeams = currentTeams.length;
        if (numTeams < 2) {
            bracketVisualContainer.innerHTML = `
                <div style="padding: 4rem 1.5rem; color: var(--text-muted); text-align: center; width: 100%;">
                    <div style="font-size: 2.5rem; margin-bottom: 0.8rem; opacity: 0.5;">⚔️</div>
                    <h4 style="font-family: var(--font-heading); margin-bottom: 0.4rem; color: var(--text-secondary); font-size: 1.1rem;">
                        Empty Bracket Canvas
                    </h4>
                    <p style="font-size: 0.85rem; max-width: 420px; margin: 0 auto; line-height: 1.5;">
                        Add at least 2 teams, upload a roster CSV/TXT, or select a quick size preset (⚡ 4, ⚡ 8, ⚡ 16, etc.) to generate and preview the live bracket tree.
                    </p>
                </div>
            `;
            bracketVisualContainer.style.minHeight = "360px";
            return;
        }

        // Title update
        const titleInput = document.getElementById("studioTournamentName");
        const previewTitle = document.getElementById("previewTitle");
        if (titleInput && previewTitle) previewTitle.textContent = titleInput.value || "Championship Series 2026";

        const championBadgeBox = document.getElementById("championBadgeBox");
        const championNameEl = document.getElementById("championName");
        if (championBadgeBox) championBadgeBox.style.display = "none";

        const bracketType = bracketTypeSelect ? bracketTypeSelect.value : "single_elimination";

        if (bracketType === "group_stage") {
            const groupCountOpt = document.getElementById("studioGroupCount") ? document.getElementById("studioGroupCount").value : "auto";
            const groupAdvOpt = document.getElementById("studioGroupAdvanceCount") ? document.getElementById("studioGroupAdvanceCount").value : "1";
            const groupData = buildGroupStageTournament(currentTeams, groupCountOpt, groupAdvOpt);
            renderGroupStageDOM(bracketVisualContainer, groupData, true, championBadgeBox, championNameEl);
        } else {
            // Challonge Single Elimination (Play-ins in Round 1 aligned with Round 2, Round 2 waiting slots, Round 3.. Semifinals.. Final)
            const rounds = buildChallongeBracketTree(currentTeams);
            renderBracketTreeDOM(bracketVisualContainer, rounds, true, championBadgeBox, championNameEl);
        }
    }

    if (generateBtn) {
        generateBtn.addEventListener("click", () => {
            generateAnimatedBracket();
            if (feedbackBox) {
                feedbackBox.style.color = "#34d399";
                feedbackBox.textContent = "⚡ Tournament generated! Edit scores and advance winners.";
            }
        });
    }

    // Initial render
    generateAnimatedBracket();

    // Bracket Engine Switcher
    const engineWebBtn = document.getElementById("engineWebBtn");
    const engineChallongeBtn = document.getElementById("engineChallongeBtn");
    const webBracketInfoBox = document.getElementById("webBracketInfoBox");
    const challongeApiBox = document.getElementById("challongeApiBox");
    const createOnChallongeBtn = document.getElementById("createOnChallongeBtn");
    const challongeFeedback = document.getElementById("challongeApiFeedback");
    let currentEngine = "web";

    if (engineWebBtn && engineChallongeBtn) {
        engineWebBtn.addEventListener("click", () => {
            engineWebBtn.classList.add("active");
            engineChallongeBtn.classList.remove("active");
            if (webBracketInfoBox) webBracketInfoBox.style.display = "block";
            if (challongeApiBox) challongeApiBox.style.display = "none";
            currentEngine = "web";
        });

        engineChallongeBtn.addEventListener("click", () => {
            engineChallongeBtn.classList.add("active");
            engineWebBtn.classList.remove("active");
            if (webBracketInfoBox) webBracketInfoBox.style.display = "none";
            if (challongeApiBox) challongeApiBox.style.display = "block";
            currentEngine = "challonge";
        });
    }

    // Auto-Generate on Challonge API Button
    if (createOnChallongeBtn) {
        createOnChallongeBtn.addEventListener("click", async () => {
            const name = document.getElementById("studioTournamentName").value.trim();
            const game = document.getElementById("studioGameCategory").value;
            const bracketType = document.getElementById("studioBracketType").value;
            const apiKey = document.getElementById("studioChallongeApiKey").value.trim();
            const challongeLinkInput = document.getElementById("studioChallongeLink");

            if (!name) {
                if (challongeFeedback) {
                    challongeFeedback.style.color = "#ef4444";
                    challongeFeedback.textContent = "❌ Please enter a tournament name first.";
                }
                return;
            }

            try {
                createOnChallongeBtn.disabled = true;
                createOnChallongeBtn.textContent = "Connecting to Challonge API...";

                const res = await fetch("/api/organizer/challonge/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        tournament_name: name,
                        game_category: game,
                        bracket_type: bracketType,
                        api_key: apiKey,
                        participants: currentTeams
                    })
                });

                const data = await res.json();
                if (res.ok && data.status === "success") {
                    if (challongeLinkInput) challongeLinkInput.value = data.challonge_url;
                    if (challongeFeedback) {
                        challongeFeedback.style.color = "#34d399";
                        challongeFeedback.textContent = `✅ Created on Challonge! URL: ${data.challonge_url}`;
                    }
                } else {
                    if (challongeFeedback) {
                        challongeFeedback.style.color = "#ef4444";
                        challongeFeedback.textContent = `❌ ${data.error || "Challonge creation failed"}`;
                    }
                }
            } catch (err) {
                if (challongeFeedback) {
                    challongeFeedback.style.color = "#ef4444";
                    challongeFeedback.textContent = "❌ Network connection error.";
                }
            } finally {
                createOnChallongeBtn.disabled = false;
                createOnChallongeBtn.textContent = "⚡ Auto-Generate Bracket on Challonge API";
            }
        });
    }

    // Publish Tournament API
    if (publishBtn) {
        publishBtn.addEventListener("click", async () => {
            const name = document.getElementById("studioTournamentName").value.trim();
            const guildId = document.getElementById("studioGuildId").value;
            const game = document.getElementById("studioGameCategory").value;
            const bracketType = document.getElementById("studioBracketType").value;
            const format = document.getElementById("studioFormat").value;
            const challongeLink = document.getElementById("studioChallongeLink") ? document.getElementById("studioChallongeLink").value.trim() : "";

            if (!name) {
                if (feedbackBox) {
                    feedbackBox.style.color = "#ef4444";
                    feedbackBox.textContent = "❌ Please enter a tournament name.";
                }
                return;
            }

            try {
                publishBtn.disabled = true;
                publishBtn.textContent = "Publishing...";

                let currentTree = {};
                if (bracketType === "group_stage") {
                    const groupCountOpt = document.getElementById("studioGroupCount") ? document.getElementById("studioGroupCount").value : "auto";
                    const groupAdvOpt = document.getElementById("studioGroupAdvanceCount") ? document.getElementById("studioGroupAdvanceCount").value : "1";
                    currentTree = buildGroupStageTournament(currentTeams, groupCountOpt, groupAdvOpt);
                } else {
                    currentTree = extractBracketTreeFromDOM(bracketVisualContainer);
                }

                const res = await fetch("/api/organizer/tournaments/create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        tournament_name: name,
                        guild_id: guildId,
                        game_category: game,
                        bracket_type: bracketType,
                        format: format,
                        challonge_bracket_link: currentEngine === "challonge" ? challongeLink : "",
                        participants: currentTeams,
                        bracket_tree: currentTree
                    })
                });

                const data = await res.json();
                if (res.ok && data.status === "success") {
                    const tid = data.tournament.Tournament_ID || data.tournament.id;
                    if (feedbackBox) {
                        feedbackBox.style.color = "#34d399";
                        feedbackBox.innerHTML = `
                            🚀 <strong>Success! Tournament '${name}' created!</strong><br>
                            Public Bracket Link: <a href="/tournament/${tid}" target="_blank" style="color: var(--primary-cyan); font-weight: 700;">/tournament/${tid}</a>
                        `;
                    }
                    setTimeout(() => window.location.href = `/tournament/${tid}`, 1200);
                } else {
                    if (feedbackBox) {
                        feedbackBox.style.color = "#ef4444";
                        feedbackBox.textContent = `❌ ${data.error || "Failed to publish tournament"}`;
                    }
                    publishBtn.disabled = false;
                    publishBtn.textContent = "🚀 Save & Publish Tournament";
                }
            } catch (err) {
                if (feedbackBox) {
                    feedbackBox.style.color = "#ef4444";
                    feedbackBox.textContent = "❌ Connection error";
                }
                publishBtn.disabled = false;
                publishBtn.textContent = "🚀 Save & Publish Tournament";
            }
        });
    }
}

// =========================================================================
// PUBLIC TOURNAMENT LIVE BRACKET VIEWER & SCORE MANAGER (/tournament/<id>)
// =========================================================================
function initPublicTournamentBracketViewer() {
    const publicStage = document.getElementById("publicBracketVisualContainer");
    const dataScript = document.getElementById("publicTournamentDataJson");
    if (!publicStage || !dataScript) return;

    let tournamentData = {};
    try {
        tournamentData = JSON.parse(dataScript.textContent || "{}");
    } catch (e) {
        console.error("Could not parse tournament data", e);
        return;
    }

    const saveBtn = document.getElementById("saveLiveBracketBtn");
    const saveStatus = document.getElementById("liveBracketSaveStatus");
    const isOrganizer = !!saveBtn;
    const champBadge = document.getElementById("publicChampionBadgeBox");
    const champNameEl = document.getElementById("publicChampionName");

    const participants = Array.isArray(tournamentData.participants) ? tournamentData.participants : [];
    const isGroupType = tournamentData.bracket_type === "group_stage" || (tournamentData.bracket_tree && tournamentData.bracket_tree.is_group_stage);

    if (isGroupType) {
        let groupData = tournamentData.bracket_tree && tournamentData.bracket_tree.groups ? tournamentData.bracket_tree : null;
        if (!groupData) {
            groupData = buildGroupStageTournament(participants, "auto", "1");
        }
        renderGroupStageDOM(publicStage, groupData, isOrganizer, champBadge, champNameEl);
        return;
    }

    const savedTree = tournamentData.bracket_tree && tournamentData.bracket_tree.rounds && tournamentData.bracket_tree.rounds.length > 0
        ? tournamentData.bracket_tree.rounds
        : null;

    if (!savedTree && participants.length < 2) {
        publicStage.innerHTML = `
            <div style="padding: 4rem 2rem; text-align: center; color: var(--text-secondary); width: 100%;">
                <div style="font-size: 3rem; margin-bottom: 1rem;">🏆</div>
                <h3 style="font-family: var(--font-heading); margin-bottom: 0.5rem;">Bracket is being seeded</h3>
                <p style="font-size: 0.9rem;">Once the tournament organizer finalizes roster check-ins, the live bracket will appear here automatically.</p>
            </div>
        `;
        return;
    }

    let rounds = [];
    if (savedTree && savedTree.length > 0) {
        rounds = savedTree;
    } else {
        rounds = buildChallongeBracketTree(participants);
    }

    // Render tree to publicStage
    renderBracketTreeDOM(publicStage, rounds, isOrganizer, champBadge, champNameEl);

    // Save button event handler
    if (saveBtn) {
        saveBtn.addEventListener("click", async () => {
            const tid = saveBtn.getAttribute("data-tid");
            const currentTree = extractBracketTreeFromDOM(publicStage);

            try {
                saveBtn.disabled = true;
                saveBtn.textContent = "Saving...";
                if (saveStatus) saveStatus.textContent = "";

                const res = await fetch(`/api/organizer/tournaments/${tid}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        bracket_tree: currentTree
                    })
                });

                const data = await res.json();
                if (res.ok && data.status === "success") {
                    if (saveStatus) {
                        saveStatus.style.color = "#34d399";
                        saveStatus.textContent = "✅ Saved successfully!";
                        setTimeout(() => { if (saveStatus) saveStatus.textContent = ""; }, 3000);
                    }
                } else {
                    if (saveStatus) {
                        saveStatus.style.color = "#ef4444";
                        saveStatus.textContent = `❌ ${data.error || "Failed to save"}`;
                    }
                }
            } catch (err) {
                if (saveStatus) {
                    saveStatus.style.color = "#ef4444";
                    saveStatus.textContent = "❌ Connection error";
                }
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = "💾 Save Match Scores & Winners";
            }
        });
    }
}

// =========================================================================
// HELPER: BUILD EXACT CHALLONGE.COM SINGLE-ELIMINATION BRACKET TREE
// =========================================================================
function buildChallongeBracketTree(participants) {
    const N = Math.min(participants.length, 256);
    if (N < 2) return [];

    // Find next power of 2
    let P = 2;
    while (P < N && P < 256) {
        P *= 2;
    }
    const totalRounds = Math.log2(P);

    function getSeedingOrder(size) {
        let seeds = [1, 2];
        while (seeds.length < size) {
            const nextLength = seeds.length * 2;
            const nextSeeds = [];
            for (let i = 0; i < seeds.length; i++) {
                nextSeeds.push(seeds[i]);
                nextSeeds.push(nextLength + 1 - seeds[i]);
            }
            seeds = nextSeeds;
        }
        return seeds;
    }

    function getRoundName(rIdx, total) {
        if (rIdx === total - 1) return "🏆 Final";
        if (rIdx === total - 2) return "⚡ Semifinals";
        return `⚔️ Round ${rIdx + 1}`;
    }

    const seedOrder = getSeedingOrder(P);
    const numInitialPairings = P / 2;
    const hasPrelim = (N < P);

    const CARD_HEIGHT = 64;
    const CARD_GAP = 20;
    const UNIT_PITCH = CARD_HEIGHT + CARD_GAP; // 84px

    const initialPairings = [];
    const r1MatchesList = [];
    let matchNumberTracker = 1;

    for (let k = 0; k < numInitialPairings; k++) {
        const s1 = seedOrder[k * 2];
        const s2 = seedOrder[k * 2 + 1];
        const team1 = s1 <= N ? (participants[s1 - 1] || `Team ${s1}`) : null;
        const team2 = s2 <= N ? (participants[s2 - 1] || `Team ${s2}`) : null;

        if (team1 && team2) {
            // Both are seeded teams -> Play-in match in Round 1
            const targetMatchIdx = Math.floor(k / 2);
            const targetSlotIdx = k % 2;
            const r2Y = targetMatchIdx * UNIT_PITCH;
            const yPos = targetSlotIdx === 0 ? (r2Y - 14) : (r2Y + 28);

            const matchObj = {
                match_id: `0-${r1MatchesList.length}`,
                match_number: matchNumberTracker++,
                pairing_index: k,
                target_round: 1,
                target_match: targetMatchIdx,
                target_slot: targetSlotIdx,
                top_y: yPos,
                seed1: s1,
                team1: team1,
                score1: 0,
                winner1: false,
                seed2: s2,
                team2: team2,
                score2: 0,
                winner2: false
            };
            r1MatchesList.push(matchObj);
            initialPairings.push({ is_match: true, match: matchObj });
        } else if (team1 && !team2) {
            // Team 1 gets pushed to Round 2 to wait for Round 1 winner
            initialPairings.push({ is_match: false, seed: s1, team: team1 });
        } else if (team2 && !team1) {
            // Team 2 gets pushed to Round 2 to wait for Round 1 winner
            initialPairings.push({ is_match: false, seed: s2, team: team2 });
        }
    }

    const rounds = [];

    if (hasPrelim) {
        // Round 1: Preliminary round with only the play-in matches aligned with Round 2
        rounds.push({
            name: "⚔️ Round 1",
            is_prelim: true,
            matches: r1MatchesList
        });

        // Round 2: P/4 matches (waiting for R1 winners to arrive)
        const numR2Matches = P / 4;
        const r2Matches = [];
        const r2Positions = [];

        for (let m = 0; m < numR2Matches; m++) {
            const topPairing = initialPairings[m * 2];
            const bottomPairing = initialPairings[m * 2 + 1];

            const topSeed = topPairing && !topPairing.is_match ? topPairing.seed : null;
            const topTeam = topPairing && !topPairing.is_match ? topPairing.team : "TBD";

            const bottomSeed = bottomPairing && !bottomPairing.is_match ? bottomPairing.seed : null;
            const bottomTeam = bottomPairing && !bottomPairing.is_match ? bottomPairing.team : "TBD";

            const yPos = m * UNIT_PITCH;
            r2Positions.push(yPos);

            r2Matches.push({
                match_id: `1-${m}`,
                match_number: matchNumberTracker++,
                top_y: yPos,
                seed1: topSeed,
                team1: topTeam,
                score1: 0,
                winner1: false,
                seed2: bottomSeed,
                team2: bottomTeam,
                score2: 0,
                winner2: false
            });
        }

        rounds.push({
            name: "⚔️ Round 2",
            matches: r2Matches
        });

        // Regular subsequent rounds from R3 up to Semifinals and Final
        let currentCount = numR2Matches / 2;
        let rIndex = 2;
        let prevPositions = r2Positions;

        while (currentCount >= 1) {
            const rMatches = [];
            const currPositions = [];

            for (let m = 0; m < currentCount; m++) {
                const yTop = prevPositions[m * 2];
                const yBottom = prevPositions[m * 2 + 1];
                const yPos = (yTop + yBottom) / 2;
                currPositions.push(yPos);

                rMatches.push({
                    match_id: `${rIndex}-${m}`,
                    match_number: matchNumberTracker++,
                    top_y: yPos,
                    seed1: null,
                    team1: "TBD",
                    score1: 0,
                    winner1: false,
                    seed2: null,
                    team2: "TBD",
                    score2: 0,
                    winner2: false
                });
            }

            rounds.push({
                name: getRoundName(rIndex, totalRounds),
                matches: rMatches
            });

            prevPositions = currPositions;
            currentCount /= 2;
            rIndex++;
        }
    } else {
        // No preliminary round (Exact power of 2)
        const numR1Matches = numInitialPairings;
        const r1Matches = [];
        const r1Positions = [];

        for (let k = 0; k < numR1Matches; k++) {
            const s1 = seedOrder[k * 2];
            const s2 = seedOrder[k * 2 + 1];
            const yPos = k * UNIT_PITCH;
            r1Positions.push(yPos);

            r1Matches.push({
                match_id: `0-${k}`,
                match_number: matchNumberTracker++,
                top_y: yPos,
                seed1: s1,
                team1: participants[s1 - 1] || `Team ${s1}`,
                score1: 0,
                winner1: false,
                seed2: s2,
                team2: participants[s2 - 1] || `Team ${s2}`,
                score2: 0,
                winner2: false
            });
        }

        rounds.push({
            name: "⚔️ Round 1",
            matches: r1Matches
        });

        let currentCount = numR1Matches / 2;
        let rIndex = 1;
        let prevPositions = r1Positions;

        while (currentCount >= 1) {
            const rMatches = [];
            const currPositions = [];

            for (let m = 0; m < currentCount; m++) {
                const yTop = prevPositions[m * 2];
                const yBottom = prevPositions[m * 2 + 1];
                const yPos = (yTop + yBottom) / 2;
                currPositions.push(yPos);

                rMatches.push({
                    match_id: `${rIndex}-${m}`,
                    match_number: matchNumberTracker++,
                    top_y: yPos,
                    seed1: null,
                    team1: "TBD",
                    score1: 0,
                    winner1: false,
                    seed2: null,
                    team2: "TBD",
                    score2: 0,
                    winner2: false
                });
            }

            rounds.push({
                name: getRoundName(rIndex, totalRounds),
                matches: rMatches
            });

            prevPositions = currPositions;
            currentCount /= 2;
            rIndex++;
        }
    }

    return rounds;
}

// =========================================================================
// =========================================================================
// HELPER: BUILD GROUP STAGE TOURNAMENT (GROUP A, B ... Z ➔ PLAYOFFS)
// =========================================================================
function buildGroupStageTournament(participants, groupCountOption, advancePerGroupOption) {
    const N = Math.min(participants.length, 256);
    if (N < 2) return { is_group_stage: true, groups: [], playoffs: [] };

    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let numGroups = 4;

    if (groupCountOption === "auto" || !groupCountOption) {
        if (N <= 4) numGroups = 2;
        else if (N <= 12) numGroups = 4;
        else if (N <= 32) numGroups = 8;
        else if (N <= 64) numGroups = 16;
        else numGroups = 26;
    } else {
        numGroups = parseInt(groupCountOption) || 4;
    }
    numGroups = Math.max(2, Math.min(numGroups, Math.min(26, N)));

    const advancePerGroup = parseInt(advancePerGroupOption) || 1;

    // Distribute teams into groups
    const groups = [];
    for (let g = 0; g < numGroups; g++) {
        groups.push({
            id: `group-${alphabet[g]}`,
            letter: alphabet[g],
            name: `Group ${alphabet[g]}`,
            teams: [],
            matches: []
        });
    }

    // Seed/distribute participants evenly
    participants.forEach((team, idx) => {
        const groupIdx = idx % numGroups;
        groups[groupIdx].teams.push({
            seed: idx + 1,
            name: team,
            played: 0,
            won: 0,
            lost: 0,
            points: 0,
            scoreDiff: 0
        });
    });

    // Build Round-Robin matches for each group
    let groupMatchCounter = 1;
    groups.forEach((g) => {
        const tList = g.teams;
        for (let i = 0; i < tList.length; i++) {
            for (let j = i + 1; j < tList.length; j++) {
                g.matches.push({
                    match_id: `${g.letter}-${i}-${j}`,
                    match_number: groupMatchCounter++,
                    group: g.letter,
                    team1: tList[i].name,
                    seed1: tList[i].seed,
                    score1: 0,
                    winner1: false,
                    team2: tList[j].name,
                    seed2: tList[j].seed,
                    score2: 0,
                    winner2: false
                });
            }
        }
    });

    // Determine playoff qualifiers (e.g. Winner Group A, Winner Group B...)
    const playoffTeams = [];
    for (let adv = 0; adv < advancePerGroup; adv++) {
        groups.forEach((g) => {
            const teamName = g.teams[adv] ? g.teams[adv].name : `Winner Group ${g.letter}`;
            playoffTeams.push(teamName);
        });
    }

    // Build Playoff Bracket for the qualifiers
    const playoffTree = buildChallongeBracketTree(playoffTeams);

    return {
        is_group_stage: true,
        advance_per_group: advancePerGroup,
        groups: groups,
        playoffs: playoffTree
    };
}

function recalculateGroupStandingsAndPlayoffs(groupData) {
    if (!groupData || !groupData.groups) return;

    const advancePerGroup = groupData.advance_per_group || 1;

    groupData.groups.forEach(g => {
        const stats = {};
        g.teams.forEach(t => {
            stats[t.name] = { seed: t.seed, name: t.name, played: 0, won: 0, lost: 0, points: 0, scoreDiff: 0 };
        });

        g.matches.forEach(m => {
            const s1 = parseInt(m.score1) || 0;
            const s2 = parseInt(m.score2) || 0;
            const hasPlayed = m.winner1 || m.winner2 || s1 > 0 || s2 > 0;

            if (hasPlayed && stats[m.team1] && stats[m.team2]) {
                stats[m.team1].played++;
                stats[m.team2].played++;
                stats[m.team1].scoreDiff += (s1 - s2);
                stats[m.team2].scoreDiff += (s2 - s1);

                if (m.winner1 || s1 > s2) {
                    stats[m.team1].won++;
                    stats[m.team1].points += 3;
                    stats[m.team2].lost++;
                } else if (m.winner2 || s2 > s1) {
                    stats[m.team2].won++;
                    stats[m.team2].points += 3;
                    stats[m.team1].lost++;
                } else {
                    stats[m.team1].points += 1;
                    stats[m.team2].points += 1;
                }
            }
        });

        g.teams = Object.values(stats).sort((a, b) => {
            if (b.points !== a.points) return b.points - a.points;
            if (b.won !== a.won) return b.won - a.won;
            if (b.scoreDiff !== a.scoreDiff) return b.scoreDiff - a.scoreDiff;
            return a.seed - b.seed;
        });
    });

    // Feed top teams into Playoff bracket
    const playoffTeams = [];
    for (let adv = 0; adv < advancePerGroup; adv++) {
        groupData.groups.forEach(g => {
            const qualifiedTeam = g.teams[adv];
            const name = qualifiedTeam ? qualifiedTeam.name : `Winner Group ${g.letter}`;
            playoffTeams.push(name);
        });
    }

    if (groupData.playoffs && groupData.playoffs.length > 0) {
        const firstRound = groupData.playoffs[0];
        if (firstRound && firstRound.matches) {
            firstRound.matches.forEach((m, mIdx) => {
                const t1 = playoffTeams[mIdx * 2];
                const t2 = playoffTeams[mIdx * 2 + 1];
                if (t1) m.team1 = t1;
                if (t2) m.team2 = t2;
            });
        }
    }
}

// =========================================================================
// RENDERER: GROUP STAGE (GROUP A, B ... Z) + KNOCKOUT PLAYOFF BRACKET
// =========================================================================
function renderGroupStageDOM(container, groupData, isEditable, champBadge, champNameEl, activeView = "all", activeGroupFilter = "all") {
    if (!container || !groupData) return;
    container.innerHTML = "";
    container.classList.add("group-stage-mode");

    const advancePerGroup = groupData.advance_per_group || 1;
    const numGroups = (groupData.groups || []).length;

    const wrapper = document.createElement("div");
    wrapper.className = "group-stage-container";

    // 1. Interactive Navigation & Filter Bar
    const navBar = document.createElement("div");
    navBar.className = "group-stage-nav-bar";
    navBar.innerHTML = `
        <div class="group-tabs-group">
            <button type="button" class="group-tab-btn ${activeView === 'all' ? 'active' : ''}" data-view="all">🌐 All Stages</button>
            <button type="button" class="group-tab-btn ${activeView === 'groups' ? 'active' : ''}" data-view="groups">📊 Groups (${numGroups})</button>
            <button type="button" class="group-tab-btn ${activeView === 'playoffs' ? 'active' : ''}" data-view="playoffs">🔥 Playoff Bracket</button>
        </div>
        <div class="group-tabs-group">
            <span style="font-size: 0.72rem; color: #64748b; font-weight: 700; text-transform: uppercase;">Filter:</span>
            <button type="button" class="group-tab-btn ${activeGroupFilter === 'all' ? 'active' : ''}" data-group-filter="all">All</button>
            ${(groupData.groups || []).map(g => `
                <button type="button" class="group-tab-btn ${activeGroupFilter === g.letter ? 'active' : ''}" data-group-filter="${g.letter}">${g.letter}</button>
            `).join("")}
        </div>
    `;
    wrapper.appendChild(navBar);

    // 2. Group Stage Grid (Group A, Group B, Group C... Group Z)
    if (activeView === "all" || activeView === "groups") {
        const grid = document.createElement("div");
        grid.className = "group-stage-grid";

        (groupData.groups || []).forEach(g => {
            if (activeGroupFilter !== "all" && activeGroupFilter !== g.letter) return;

            const card = document.createElement("div");
            card.className = "group-card";
            card.innerHTML = `
                <div class="group-card-header">
                    <div class="group-card-title">🏆 ${g.name}</div>
                    <div class="group-team-badge">${g.teams.length} Teams &bull; Top ${advancePerGroup} Qualify</div>
                </div>
                <table class="group-standings-table">
                    <thead>
                        <tr>
                            <th style="width: 28px;">#</th>
                            <th>Team</th>
                            <th style="text-align: center; width: 28px;">P</th>
                            <th style="text-align: center; width: 28px;">W</th>
                            <th style="text-align: center; width: 28px;">L</th>
                            <th style="text-align: right; width: 34px;">Pts</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${g.teams.map((t, idx) => {
                            const isQualifying = idx < advancePerGroup;
                            return `
                                <tr class="${isQualifying ? 'qualifying-team' : ''}">
                                    <td style="font-family: var(--font-mono); color: ${isQualifying ? '#34d399' : '#64748b'}; font-weight: 700;">${idx + 1}</td>
                                    <td>
                                        <span style="font-weight: 600;">${t.name}</span>
                                        ${isQualifying ? '<span class="group-qualify-tag">🟢 Advancing</span>' : ''}
                                    </td>
                                    <td style="text-align: center; font-family: var(--font-mono);">${t.played}</td>
                                    <td style="text-align: center; font-family: var(--font-mono); color: #34d399;">${t.won}</td>
                                    <td style="text-align: center; font-family: var(--font-mono); color: #ef4444;">${t.lost}</td>
                                    <td style="text-align: right; font-family: var(--font-mono); font-weight: 800; color: var(--primary-cyan);">${t.points}</td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
                <div style="font-size: 0.72rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">⚔️ Group Matches</div>
                <div class="group-matches-list">
                    ${g.matches.map((m, mIdx) => `
                        <div class="group-match-item" data-group="${g.letter}" data-match="${mIdx}">
                            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; flex: 1;">
                                <span style="font-size: 0.7rem; color: #64748b; font-family: var(--font-mono);">#${m.match_number}</span>
                                <span style="font-weight: ${m.winner1 ? '700' : '500'}; color: ${m.winner1 ? '#34d399' : '#f1f5f9'};">${m.team1}</span>
                                <span style="color: #64748b; font-size: 0.7rem;">vs</span>
                                <span style="font-weight: ${m.winner2 ? '700' : '500'}; color: ${m.winner2 ? '#34d399' : '#f1f5f9'};">${m.team2}</span>
                            </div>
                            ${isEditable ? `
                                <div style="display: flex; align-items: center; gap: 3px;">
                                    <input type="number" class="bracket-score-input group-score-1" value="${m.score1}" min="0" max="999" style="width: 32px; height: 22px; font-size: 0.75rem;">
                                    <button type="button" class="bracket-advance-btn group-win-1-btn" style="height: 22px; padding: 1px 4px; font-size: 0.65rem;" title="Mark ${m.team1} Winner">▶</button>
                                    <span style="color: #475569;">-</span>
                                    <input type="number" class="bracket-score-input group-score-2" value="${m.score2}" min="0" max="999" style="width: 32px; height: 22px; font-size: 0.75rem;">
                                    <button type="button" class="bracket-advance-btn group-win-2-btn" style="height: 22px; padding: 1px 4px; font-size: 0.65rem;" title="Mark ${m.team2} Winner">▶</button>
                                </div>
                            ` : `
                                <span class="bracket-score-display" style="font-size: 0.75rem;">${m.score1} - ${m.score2}</span>
                            `}
                        </div>
                    `).join("")}
                </div>
            `;
            grid.appendChild(card);
        });
        wrapper.appendChild(grid);
    }

    // 3. Playoff / Knockout Bracket (Group Winners ➔ Semifinals ➔ Finals)
    if ((activeView === "all" || activeView === "playoffs") && groupData.playoffs && groupData.playoffs.length > 0) {
        const playoffSection = document.createElement("div");
        playoffSection.className = "group-playoff-divider";
        playoffSection.innerHTML = `
            <div class="group-playoff-title">
                <span>🔥 Playoff Knockout Stage &bull; Group Winners Meet in Semifinals & Finals</span>
            </div>
        `;

        const playoffStage = document.createElement("div");
        playoffStage.className = "bracket-visual-stage";
        playoffStage.id = "groupPlayoffsStage";
        playoffSection.appendChild(playoffStage);
        wrapper.appendChild(playoffSection);

        // Render the playoff bracket inside playoffStage
        renderBracketTreeDOM(playoffStage, groupData.playoffs, isEditable, champBadge, champNameEl);
    }

    container.appendChild(wrapper);

    // Bind navigation tab clicks
    navBar.querySelectorAll("[data-view]").forEach(btn => {
        btn.addEventListener("click", () => {
            const v = btn.getAttribute("data-view");
            renderGroupStageDOM(container, groupData, isEditable, champBadge, champNameEl, v, activeGroupFilter);
        });
    });

    navBar.querySelectorAll("[data-group-filter]").forEach(btn => {
        btn.addEventListener("click", () => {
            const f = btn.getAttribute("data-group-filter");
            renderGroupStageDOM(container, groupData, isEditable, champBadge, champNameEl, activeView, f);
        });
    });

    if (!isEditable) return;

    // Handle group match score edits and winner clicks
    wrapper.querySelectorAll(".group-win-1-btn, .group-win-2-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            const item = btn.closest(".group-match-item");
            const gLetter = item.getAttribute("data-group");
            const mIdx = parseInt(item.getAttribute("data-match"));
            const isTeam1 = btn.classList.contains("group-win-1-btn");

            const grp = groupData.groups.find(g => g.letter === gLetter);
            if (!grp || !grp.matches[mIdx]) return;

            const m = grp.matches[mIdx];
            m.winner1 = isTeam1;
            m.winner2 = !isTeam1;
            if (isTeam1 && m.score1 <= m.score2) m.score1 = m.score2 + 1;
            if (!isTeam1 && m.score2 <= m.score1) m.score2 = m.score1 + 1;

            recalculateGroupStandingsAndPlayoffs(groupData);
            renderGroupStageDOM(container, groupData, isEditable, champBadge, champNameEl, activeView, activeGroupFilter);
        });
    });

    wrapper.querySelectorAll(".group-score-1, .group-score-2").forEach(input => {
        input.addEventListener("change", () => {
            const item = input.closest(".group-match-item");
            const gLetter = item.getAttribute("data-group");
            const mIdx = parseInt(item.getAttribute("data-match"));
            const grp = groupData.groups.find(g => g.letter === gLetter);
            if (!grp || !grp.matches[mIdx]) return;

            const m = grp.matches[mIdx];
            const s1 = parseInt(item.querySelector(".group-score-1").value) || 0;
            const s2 = parseInt(item.querySelector(".group-score-2").value) || 0;
            m.score1 = s1;
            m.score2 = s2;
            m.winner1 = (s1 > s2);
            m.winner2 = (s2 > s1);

            recalculateGroupStandingsAndPlayoffs(groupData);
            renderGroupStageDOM(container, groupData, isEditable, champBadge, champNameEl, activeView, activeGroupFilter);
        });
    });
}

// =========================================================================
// SVG BRACKET CONNECTOR LINE GENERATOR & ANIMATION (CHALLONGE STYLE)
// =========================================================================
function drawBracketSvgConnectors(container) {
    if (!container) return;
    let svgLayer = container.querySelector(".bracket-svg-layer");
    if (!svgLayer) {
        svgLayer = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svgLayer.setAttribute("class", "bracket-svg-layer");
        container.insertBefore(svgLayer, container.firstChild);
    }
    svgLayer.innerHTML = "";

    const containerRect = container.getBoundingClientRect();
    svgLayer.style.width = `${container.scrollWidth}px`;
    svgLayer.style.height = `${container.scrollHeight}px`;

    const cols = Array.from(container.querySelectorAll(".bracket-round-col"));
    if (cols.length < 2) return;

    const isR1Prelim = cols[0].hasAttribute("data-is-prelim");

    cols.forEach((currentCol, rIdx) => {
        if (rIdx >= cols.length - 1) return;
        const nextCol = cols[rIdx + 1];
        const currentNodes = currentCol.querySelectorAll(".bracket-match-node");
        const nextNodes = nextCol.querySelectorAll(".bracket-match-node");

        currentNodes.forEach((node) => {
            let targetNode = null;
            let targetSlotIdx = 0;

            if (rIdx === 0 && isR1Prelim) {
                const targetMatchIdx = parseInt(node.getAttribute("data-target-match") || "0");
                targetSlotIdx = parseInt(node.getAttribute("data-target-slot") || "0");
                targetNode = nextCol.querySelector(`#match-1-${targetMatchIdx}`);
            } else {
                const mIdx = parseInt(node.getAttribute("data-match-index") || "0");
                const nextMatchIdx = Math.floor(mIdx / 2);
                targetSlotIdx = mIdx % 2;
                targetNode = nextNodes[nextMatchIdx];
            }

            if (!targetNode) return;

            const nRect = node.getBoundingClientRect();
            const tRect = targetNode.getBoundingClientRect();

            // Source point: center-right of current match node
            const x1 = (nRect.right - containerRect.left) + container.scrollLeft;
            const y1 = (nRect.top + nRect.height / 2 - containerRect.top) + container.scrollTop;

            // Target point: center-left of target match node slot
            const x2 = (tRect.left - containerRect.left) + container.scrollLeft;
            const y2 = (tRect.top + (targetSlotIdx === 0 ? tRect.height * 0.28 : tRect.height * 0.72) - containerRect.top) + container.scrollTop;

            const xMid = x1 + (x2 - x1) * 0.5;

            // Smooth orthogonal bracket path: Start -> Mid X -> Mid Y -> End
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            const d = `M ${x1} ${y1} H ${xMid} V ${y2} H ${x2}`;
            path.setAttribute("d", d);

            // Check if this match has a crowned winner
            const hasWinner = node.querySelector(".bracket-team-slot.winner");
            path.setAttribute("class", `bracket-connector-path ${hasWinner ? 'winner-path' : ''}`);

            svgLayer.appendChild(path);
        });
    });
}

// =========================================================================
// UNIFIED BRACKET DOM RENDERER & STATE EXTRACTOR (CHALLONGE STYLE)
// =========================================================================
function renderBracketTreeDOM(container, rounds, isEditable, champBadge, champNameEl) {
    if (!container || !rounds || rounds.length === 0) return;
    container.innerHTML = "";
    container.classList.remove("group-stage-mode");

    // Determine max Y position to size stage height properly
    let maxY = 540;
    rounds.forEach(r => {
        if (r.matches) {
            r.matches.forEach(m => {
                if (m.top_y !== undefined && m.top_y > maxY - 100) {
                    maxY = m.top_y + 100;
                }
            });
        }
    });

    const stageHeight = Math.max(540, maxY);
    container.style.minHeight = `${stageHeight + 60}px`;

    rounds.forEach((round, rIdx) => {
        const col = document.createElement("div");
        col.className = "bracket-round-col";
        col.setAttribute("data-round-index", rIdx);
        if (round.is_prelim) col.setAttribute("data-is-prelim", "true");

        const header = document.createElement("div");
        header.className = "bracket-round-header";
        header.textContent = round.name;
        col.appendChild(header);

        const colBody = document.createElement("div");
        colBody.className = "bracket-round-col-body";
        colBody.style.height = `${stageHeight}px`;

        const isPrelim = !!round.is_prelim;

        round.matches.forEach((m, mIdx) => {
            const node = document.createElement("div");
            node.className = "bracket-match-node";
            node.id = `match-${rIdx}-${mIdx}`;
            node.setAttribute("data-round-index", rIdx);
            node.setAttribute("data-match-index", mIdx);
            node.style.top = `${m.top_y !== undefined ? m.top_y : (mIdx * 84)}px`;
            node.style.animationDelay = `${Math.min(1.2, (rIdx * 0.1) + (mIdx * 0.02))}s`;

            if (isPrelim) {
                node.setAttribute("data-target-round", m.target_round !== undefined ? m.target_round : 1);
                node.setAttribute("data-target-match", m.target_match !== undefined ? m.target_match : Math.floor(mIdx / 2));
                node.setAttribute("data-target-slot", m.target_slot !== undefined ? m.target_slot : (mIdx % 2));
            }

            const s1 = (m.seed1 !== null && m.seed1 !== undefined && m.seed1 !== "--") ? `${m.seed1}` : "--";
            const s2 = (m.seed2 !== null && m.seed2 !== undefined && m.seed2 !== "--") ? `${m.seed2}` : "--";
            const team1 = m.team1 || "TBD";
            const team2 = m.team2 || "TBD";
            const score1 = m.score1 !== undefined ? m.score1 : 0;
            const score2 = m.score2 !== undefined ? m.score2 : 0;
            const win1Class = m.winner1 ? "winner" : "";
            const win2Class = m.winner2 ? "winner" : "";
            const matchNumber = m.match_number !== undefined ? m.match_number : (mIdx + 1);

            const scoreOrControls1 = isEditable ? `
                <div style="display: flex; align-items: center; gap: 4px;">
                    <input type="number" class="bracket-score-input" value="${score1}" min="0" max="999" title="Edit match score">
                    <button type="button" class="bracket-advance-btn" title="Advance as Winner">▶</button>
                </div>
            ` : `
                <span class="bracket-score-display">${score1}</span>
            `;

            const scoreOrControls2 = isEditable ? `
                <div style="display: flex; align-items: center; gap: 4px;">
                    <input type="number" class="bracket-score-input" value="${score2}" min="0" max="999" title="Edit match score">
                    <button type="button" class="bracket-advance-btn" title="Advance as Winner">▶</button>
                </div>
            ` : `
                <span class="bracket-score-display">${score2}</span>
            `;

            node.innerHTML = `
                <span class="bracket-match-number">${matchNumber}</span>
                <div class="bracket-team-slot slot-top ${win1Class}" data-round="${rIdx}" data-match="${mIdx}" data-slot="0">
                    <span class="bracket-seed-badge">${s1}</span>
                    <span class="team-name" ${isEditable ? 'contenteditable="true"' : ''} title="${isEditable ? 'Click to rename team' : ''}">${team1}</span>
                    ${scoreOrControls1}
                </div>
                <div class="bracket-team-slot slot-bottom ${win2Class}" data-round="${rIdx}" data-match="${mIdx}" data-slot="1">
                    <span class="bracket-seed-badge">${s2}</span>
                    <span class="team-name" ${isEditable ? 'contenteditable="true"' : ''} title="${isEditable ? 'Click to rename team' : ''}">${team2}</span>
                    ${scoreOrControls2}
                </div>
            `;
            colBody.appendChild(node);
        });

        col.appendChild(colBody);
        container.appendChild(col);
    });

    // Draw SVG connector lines
    requestAnimationFrame(() => {
        drawBracketSvgConnectors(container);
    });

    // Check if champion is already crowned
    if (rounds.length > 0) {
        const lastRound = rounds[rounds.length - 1];
        if (lastRound && lastRound.matches && lastRound.matches.length > 0) {
            const finalMatch = lastRound.matches[0];
            if (finalMatch.winner1 && finalMatch.team1 && finalMatch.team1 !== "TBD") {
                if (champBadge && champNameEl) {
                    champNameEl.textContent = finalMatch.team1;
                    champBadge.style.display = "block";
                }
            } else if (finalMatch.winner2 && finalMatch.team2 && finalMatch.team2 !== "TBD") {
                if (champBadge && champNameEl) {
                    champNameEl.textContent = finalMatch.team2;
                    champBadge.style.display = "block";
                }
            }
        }
    }

    if (!isEditable) return;

    // Advance Slot Winner helper (Supports Challonge prelim & standard rounds)
    function advanceSlotWinner(slot) {
        const rIdx = parseInt(slot.getAttribute("data-round"));
        const mIdx = parseInt(slot.getAttribute("data-match"));
        const teamName = slot.querySelector(".team-name").textContent.trim();
        const seedBadge = slot.querySelector(".bracket-seed-badge");
        const seedText = seedBadge ? seedBadge.textContent.trim() : "--";

        if (teamName === "TBD" || teamName === "BYE" || !teamName) return;

        const parentNode = slot.closest(".bracket-match-node");
        parentNode.querySelectorAll(".bracket-team-slot").forEach(s => s.classList.remove("winner"));
        slot.classList.add("winner");

        // If finals, crown champion!
        if (rIdx === rounds.length - 1) {
            if (champBadge && champNameEl) {
                champNameEl.textContent = teamName;
                champBadge.style.display = "block";
            }
            drawBracketSvgConnectors(container);
            return;
        }

        let nextRoundIdx = rIdx + 1;
        let nextMatchIdx = Math.floor(mIdx / 2);
        let nextSlotIdx = mIdx % 2;

        if (rIdx === 0 && parentNode.hasAttribute("data-target-match")) {
            nextRoundIdx = parseInt(parentNode.getAttribute("data-target-round") || "1");
            nextMatchIdx = parseInt(parentNode.getAttribute("data-target-match") || "0");
            nextSlotIdx = parseInt(parentNode.getAttribute("data-target-slot") || "0");
        }

        const nextMatchNode = container.querySelector(`#match-${nextRoundIdx}-${nextMatchIdx}`);
        if (nextMatchNode) {
            const targetSlots = nextMatchNode.querySelectorAll(".bracket-team-slot");
            if (targetSlots[nextSlotIdx]) {
                const nameSpan = targetSlots[nextSlotIdx].querySelector(".team-name");
                const badgeSpan = targetSlots[nextSlotIdx].querySelector(".bracket-seed-badge");
                if (nameSpan) nameSpan.textContent = teamName;
                if (badgeSpan && seedText !== "--") badgeSpan.textContent = seedText;

                targetSlots[nextSlotIdx].style.animation = "none";
                setTimeout(() => targetSlots[nextSlotIdx].style.animation = "matchNodePop 0.3s ease", 10);
            }
        }

        // Redraw SVG connector lines to show updated winner path
        drawBracketSvgConnectors(container);
    }

    container.querySelectorAll(".bracket-advance-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const slot = btn.closest(".bracket-team-slot");
            advanceSlotWinner(slot);
        });
    });

    container.querySelectorAll(".bracket-team-slot").forEach(slot => {
        slot.addEventListener("click", (e) => {
            if (e.target.tagName === "INPUT" || e.target.getAttribute("contenteditable") === "true") {
                return;
            }
            advanceSlotWinner(slot);
        });
    });

    // Auto-advance or update winner on score input changes
    container.querySelectorAll(".bracket-score-input").forEach(input => {
        input.addEventListener("change", (e) => {
            const node = input.closest(".bracket-match-node");
            const topSlot = node.querySelector(".slot-top");
            const bottomSlot = node.querySelector(".slot-bottom");
            const score1 = parseInt(topSlot.querySelector(".bracket-score-input").value) || 0;
            const score2 = parseInt(bottomSlot.querySelector(".bracket-score-input").value) || 0;

            if (score1 > score2 && score1 > 0) {
                advanceSlotWinner(topSlot);
            } else if (score2 > score1 && score2 > 0) {
                advanceSlotWinner(bottomSlot);
            }
        });
    });

    // Window resize event to keep SVG connectors aligned
    if (!window._bracketResizeBound) {
        window._bracketResizeBound = true;
        window.addEventListener("resize", () => {
            document.querySelectorAll(".bracket-visual-stage").forEach(stg => {
                drawBracketSvgConnectors(stg);
            });
        });
    }
}

function extractBracketTreeFromDOM(container) {
    if (!container) return { rounds: [] };
    const rounds = [];
    container.querySelectorAll(".bracket-round-col").forEach((col, rIdx) => {
        const header = col.querySelector(".bracket-round-header");
        const roundName = header ? header.textContent.trim() : `Round ${rIdx + 1}`;
        const isPrelim = col.hasAttribute("data-is-prelim");
        const matches = [];

        col.querySelectorAll(".bracket-match-node").forEach((node, mIdx) => {
            const topSlot = node.querySelector(".slot-top");
            const bottomSlot = node.querySelector(".slot-bottom");
            const matchNumEl = node.querySelector(".bracket-match-number");

            const s1Badge = topSlot ? topSlot.querySelector(".bracket-seed-badge") : null;
            const s2Badge = bottomSlot ? bottomSlot.querySelector(".bracket-seed-badge") : null;
            const t1Span = topSlot ? topSlot.querySelector(".team-name") : null;
            const t2Span = bottomSlot ? bottomSlot.querySelector(".team-name") : null;
            const sc1Input = topSlot ? topSlot.querySelector(".bracket-score-input, .bracket-score-display") : null;
            const sc2Input = bottomSlot ? bottomSlot.querySelector(".bracket-score-input, .bracket-score-display") : null;

            const sc1Val = sc1Input ? (sc1Input.value !== undefined ? (parseInt(sc1Input.value) || 0) : (parseInt(sc1Input.textContent) || 0)) : 0;
            const sc2Val = sc2Input ? (sc2Input.value !== undefined ? (parseInt(sc2Input.value) || 0) : (parseInt(sc2Input.textContent) || 0)) : 0;

            const matchObj = {
                match_id: `${rIdx}-${mIdx}`,
                match_number: matchNumEl ? parseInt(matchNumEl.textContent.trim()) : (mIdx + 1),
                seed1: s1Badge ? s1Badge.textContent.trim().replace(/^S/, '') : "--",
                team1: t1Span ? t1Span.textContent.trim() : "TBD",
                score1: sc1Val,
                winner1: topSlot ? topSlot.classList.contains("winner") : false,
                seed2: s2Badge ? s2Badge.textContent.trim().replace(/^S/, '') : "--",
                team2: t2Span ? t2Span.textContent.trim() : "TBD",
                score2: sc2Val,
                winner2: bottomSlot ? bottomSlot.classList.contains("winner") : false
            };

            if (isPrelim && node.hasAttribute("data-target-match")) {
                matchObj.target_round = parseInt(node.getAttribute("data-target-round") || "1");
                matchObj.target_match = parseInt(node.getAttribute("data-target-match") || "0");
                matchObj.target_slot = parseInt(node.getAttribute("data-target-slot") || "0");
            }

            matches.push(matchObj);
        });

        rounds.push({
            name: roundName,
            is_prelim: isPrelim,
            matches: matches
        });
    });
    return { rounds: rounds };
}

// =========================================================================
// TOURNAMENT TABLE ACTIONS: EDIT, DELETE & COPY LINK
// =========================================================================
function initTournamentTableActions() {
    const editModal = document.getElementById("editTournamentModal");
    const editForm = document.getElementById("quickEditTourneyForm");
    const closeBtn = document.getElementById("closeEditModalBtn");
    const cancelBtn = document.getElementById("cancelEditModalBtn");
    const feedback = document.getElementById("editTourneyFeedback");

    const editIdInput = document.getElementById("editTourneyId");
    const editNameInput = document.getElementById("editTourneyName");
    const editGameInput = document.getElementById("editTourneyGame");
    const editStateInput = document.getElementById("editTourneyState");
    const editChallongeInput = document.getElementById("editTourneyChallonge");

    function closeModal() {
        if (editModal) editModal.style.display = "none";
        if (feedback) feedback.textContent = "";
    }

    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (cancelBtn) cancelBtn.addEventListener("click", closeModal);

    // Bind Copy Link Buttons
    document.querySelectorAll(".btn-copy-link").forEach(btn => {
        btn.addEventListener("click", async () => {
            const rawLink = btn.getAttribute("data-link");
            const fullUrl = rawLink.startsWith("http") ? rawLink : window.location.origin + rawLink;
            try {
                await navigator.clipboard.writeText(fullUrl);
                const prev = btn.textContent;
                btn.textContent = "✅";
                setTimeout(() => btn.textContent = prev, 1500);
            } catch (e) {
                prompt("Copy public tournament link:", fullUrl);
            }
        });
    });

    // Bind Edit Buttons
    document.querySelectorAll(".edit-tourney-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const tid = btn.getAttribute("data-tid");
            const name = btn.getAttribute("data-name");
            const game = btn.getAttribute("data-game");
            const state = btn.getAttribute("data-state");
            const challonge = btn.getAttribute("data-challonge");

            if (editIdInput) editIdInput.value = tid;
            if (editNameInput) editNameInput.value = name;
            if (editGameInput) editGameInput.value = game;
            if (editStateInput) editStateInput.value = state;
            if (editChallongeInput) editChallongeInput.value = challonge;

            if (editModal) editModal.style.display = "flex";
        });
    });

    // Save Edit Form
    if (editForm) {
        editForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const tid = editIdInput.value;
            const payload = {
                Tournament_Name: editNameInput.value.trim(),
                game_category: editGameInput.value.trim(),
                State: editStateInput.value,
                challonge_bracket_link: editChallongeInput.value.trim()
            };

            try {
                const res = await fetch(`/api/organizer/tournaments/${tid}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok && data.status === "success") {
                    if (feedback) {
                        feedback.style.color = "#34d399";
                        feedback.textContent = "✅ Tournament updated successfully!";
                    }
                    setTimeout(() => location.reload(), 900);
                } else {
                    if (feedback) {
                        feedback.style.color = "#ef4444";
                        feedback.textContent = `❌ ${data.error || "Failed to update"}`;
                    }
                }
            } catch (err) {
                if (feedback) {
                    feedback.style.color = "#ef4444";
                    feedback.textContent = "❌ Connection error";
                }
            }
        });
    }

    // Bind Delete Buttons
    document.querySelectorAll(".delete-tourney-btn").forEach(btn => {
        btn.addEventListener("click", async () => {
            const tid = btn.getAttribute("data-tid");
            const name = btn.getAttribute("data-name");

            if (!confirm(`Are you sure you want to permanently delete tournament '${name}' (ID: ${tid})?`)) {
                return;
            }

            try {
                const res = await fetch(`/api/organizer/tournaments/${tid}`, {
                    method: "DELETE"
                });
                const data = await res.json();
                if (res.ok && data.status === "success") {
                    const row = document.getElementById(`tourney-row-${tid}`);
                    if (row) {
                        row.style.transition = "opacity 0.4s ease, transform 0.4s ease";
                        row.style.opacity = "0";
                        row.style.transform = "translateX(20px)";
                        setTimeout(() => row.remove(), 400);
                    }
                } else {
                    alert(`Error: ${data.error || "Could not delete tournament"}`);
                }
            } catch (err) {
                alert("Connection error while deleting tournament");
            }
        });
    });
}

// =========================================================================
// SERVER CONFIGURATION & WEB COMMAND CONSOLE
// =========================================================================
function initServerConfigAndCommandConsole() {
    const serverPanel = document.getElementById("server-commands-panel");
    if (!serverPanel) return;

    const guildSelect = document.getElementById("serverSelectDropdown");
    const reloadBtn = document.getElementById("reloadServerConfigBtn");
    const configForm = document.getElementById("serverConfigForm");
    const configFeedback = document.getElementById("configSaveFeedback");

    // Command Runner elements
    const cmdInput = document.getElementById("cmdInputName");
    const cmdForm = document.getElementById("webCommandForm");
    const terminalOutput = document.getElementById("terminalLogOutput");
    const clearTermBtn = document.getElementById("clearTerminalBtn");
    const presetButtons = document.querySelectorAll(".cmd-preset-btn");
    const dynamicParamsContainer = document.getElementById("cmdDynamicParamsContainer");
    const paramMessageGroup = document.getElementById("cmdParamMessageGroup");
    const paramTeamsGroup = document.getElementById("cmdParamTeamsGroup");

    // Load Guild Configuration
    async function loadGuildConfig(guildId) {
        if (!guildId) return;
        try {
            const res = await fetch(`/api/organizer/guild-config?guild_id=${guildId}`);
            const data = await res.json();
            if (res.ok && data.status === "success" && data.config) {
                const cfg = data.config;
                const orgNameInput = document.getElementById("cfgOrgName");
                const botNameInput = document.getElementById("cfgBotName");
                if (orgNameInput) orgNameInput.value = cfg.organization_name || "";
                if (botNameInput) botNameInput.value = cfg.tournament_system_name || "";

                // Roles
                const roles = cfg.role_ids || {};
                const rAdmin = document.getElementById("cfgRoleAdmin");
                const rOrg = document.getElementById("cfgRoleOrganizer");
                const rHelp = document.getElementById("cfgRoleHelper");
                const rJudge = document.getElementById("cfgRoleJudge");
                const rRec = document.getElementById("cfgRoleRecorder");
                const rStaff = document.getElementById("cfgRoleStaff");
                const rPlay = document.getElementById("cfgRolePlayers");
                if (rAdmin) rAdmin.value = roles.head_organizer || "";
                if (rOrg) rOrg.value = roles.organizer || "";
                if (rHelp) rHelp.value = roles.helper_team || "";
                if (rJudge) rJudge.value = roles.judge || "";
                if (rRec) rRec.value = roles.recorder || "";
                if (rStaff) rStaff.value = roles.staff || "";
                if (rPlay) rPlay.value = roles.players || "";

                // Channels
                const chans = cfg.channel_ids || {};
                const cRules = document.getElementById("cfgChanRules");
                const cBracket = document.getElementById("cfgChanBracket");
                const cResults = document.getElementById("cfgChanResults");
                const cSched = document.getElementById("cfgChanSchedule");
                const cBotLogs = document.getElementById("cfgChanBotLogs");
                const cChalLogs = document.getElementById("cfgChanChallongeLogs");
                if (cRules) cRules.value = chans.rules || "";
                if (cBracket) cBracket.value = chans.bracket || "";
                if (cResults) cResults.value = chans.results || "";
                if (cSched) cSched.value = chans.take_schedule || "";
                if (cBotLogs) cBotLogs.value = chans.bot_logs || "";
                if (cChalLogs) cChalLogs.value = chans.challonge_logs || "";

                appendTerminal(`[LOAD] Loaded configuration for Server ID: ${guildId}`);
            }
        } catch (e) {
            console.error("Config fetch error:", e);
        }
    }

    if (guildSelect) {
        guildSelect.addEventListener("change", () => loadGuildConfig(guildSelect.value));
        // Initial load
        loadGuildConfig(guildSelect.value);
    }

    if (reloadBtn) {
        reloadBtn.addEventListener("click", () => {
            if (guildSelect) loadGuildConfig(guildSelect.value);
        });
    }

    // Save Server Configuration
    if (configForm) {
        configForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const guildId = guildSelect ? guildSelect.value : "1303670721796640799";

            const payload = {
                guild_id: guildId,
                organization_name: document.getElementById("cfgOrgName").value,
                tournament_system_name: document.getElementById("cfgBotName").value,
                role_ids: {
                    head_organizer: document.getElementById("cfgRoleAdmin").value,
                    organizer: document.getElementById("cfgRoleOrganizer").value,
                    helper_team: document.getElementById("cfgRoleHelper").value,
                    judge: document.getElementById("cfgRoleJudge").value,
                    recorder: document.getElementById("cfgRoleRecorder").value,
                    staff: document.getElementById("cfgRoleStaff").value,
                    players: document.getElementById("cfgRolePlayers").value
                },
                channel_ids: {
                    rules: document.getElementById("cfgChanRules").value,
                    bracket: document.getElementById("cfgChanBracket").value,
                    results: document.getElementById("cfgChanResults").value,
                    take_schedule: document.getElementById("cfgChanSchedule").value,
                    bot_logs: document.getElementById("cfgChanBotLogs").value,
                    challonge_logs: document.getElementById("cfgChanChallongeLogs").value
                }
            };

            try {
                const res = await fetch("/api/organizer/guild-config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok && data.status === "success") {
                    if (configFeedback) {
                        configFeedback.style.color = "#34d399";
                        configFeedback.textContent = "✅ Server configuration saved & synchronized!";
                    }
                    appendTerminal(`[SAVE] Updated server settings for Guild ${guildId}`);
                } else {
                    if (configFeedback) {
                        configFeedback.style.color = "#ef4444";
                        configFeedback.textContent = `❌ ${data.error || "Failed to save configuration"}`;
                    }
                }
            } catch (err) {
                if (configFeedback) {
                    configFeedback.style.color = "#ef4444";
                    configFeedback.textContent = "❌ Connection error";
                }
            }
        });
    }

    // Command Preset Button Clicks
    presetButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            presetButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const cmd = btn.getAttribute("data-cmd");
            if (cmdInput) cmdInput.value = cmd;

            if (dynamicParamsContainer) {
                if (cmd === "!announce") {
                    dynamicParamsContainer.style.display = "block";
                    if (paramMessageGroup) paramMessageGroup.style.display = "block";
                    if (paramTeamsGroup) paramTeamsGroup.style.display = "none";
                } else if (cmd === "!generate_poster") {
                    dynamicParamsContainer.style.display = "block";
                    if (paramMessageGroup) paramMessageGroup.style.display = "none";
                    if (paramTeamsGroup) paramTeamsGroup.style.display = "grid";
                } else {
                    dynamicParamsContainer.style.display = "none";
                }
            }
        });
    });

    // Terminal Logger Helper
    function appendTerminal(text) {
        if (!terminalOutput) return;
        terminalOutput.textContent += `\n${text}`;
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }

    if (clearTermBtn) {
        clearTermBtn.addEventListener("click", () => {
            if (terminalOutput) terminalOutput.textContent = "[SYSTEM] Terminal output cleared.";
        });
    }

    // Execute Command Form Handler
    if (cmdForm) {
        cmdForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const cmd = cmdInput ? cmdInput.value.trim() : "";
            const guildId = guildSelect ? guildSelect.value : "1303670721796640799";

            if (!cmd) return;

            const params = {};
            const msgEl = document.getElementById("cmdParamMessage");
            const teamAEl = document.getElementById("cmdParamTeamA");
            const teamBEl = document.getElementById("cmdParamTeamB");
            if (msgEl && msgEl.value) params.message = msgEl.value;
            if (teamAEl && teamAEl.value) params.team_a = teamAEl.value;
            if (teamBEl && teamBEl.value) params.team_b = teamBEl.value;

            appendTerminal(`> ${cmd}`);

            try {
                const res = await fetch("/api/organizer/execute-command", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        command: cmd,
                        guild_id: guildId,
                        params: params
                    })
                });

                const data = await res.json();
                if (res.ok && data.status === "success") {
                    appendTerminal(data.log_output);
                } else {
                    appendTerminal(`[ERROR] ${data.error || "Command execution failed"}`);
                }
            } catch (err) {
                appendTerminal(`[ERROR] Connection failed while executing command.`);
            }
        });
    }
}

// =========================================================================
// SPONSOR MANAGEMENT FORM
// =========================================================================
function initSponsorForm() {
    const form = document.getElementById("addSponsorForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const feedback = document.getElementById("sponsorFormFeedback");

        const payload = {
            guild_id: document.getElementById("sponsorGuildId").value,
            sponsor_name: document.getElementById("sponsorName").value,
            banner_image_url: document.getElementById("sponsorImageUrl").value,
            target_url: document.getElementById("sponsorTargetUrl").value,
            slot_position: document.getElementById("sponsorSlotPosition").value
        };

        try {
            const res = await fetch("/api/organizer/sponsors", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok && data.status === "success") {
                if (feedback) {
                    feedback.style.color = "#10b981";
                    feedback.textContent = "✅ Sponsor Banner successfully added/updated!";
                }
                setTimeout(() => location.reload(), 1200);
            } else {
                if (feedback) {
                    feedback.style.color = "#ef4444";
                    feedback.textContent = `❌ ${data.error || "Failed to save sponsor"}`;
                }
            }
        } catch (err) {
            if (feedback) {
                feedback.style.color = "#ef4444";
                feedback.textContent = "❌ Connection error";
            }
        }
    });
}

// =========================================================================
// AFFILIATE PRODUCT FORM
// =========================================================================
function initAffiliateForm() {
    const form = document.getElementById("addAffiliateForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const feedback = document.getElementById("affiliateFormFeedback");

        const payload = {
            game_category: document.getElementById("affGameCategory").value,
            product_name: document.getElementById("affProductName").value,
            product_category: document.getElementById("affProductCategory").value,
            image_url: document.getElementById("affImageUrl").value,
            affiliate_url: document.getElementById("affUrl").value,
            badge_text: document.getElementById("affBadge").value,
            price_display: document.getElementById("affPrice").value
        };

        try {
            const res = await fetch("/api/organizer/affiliates", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok && data.status === "success") {
                if (feedback) {
                    feedback.style.color = "#10b981";
                    feedback.textContent = "✅ Affiliate Card added successfully!";
                }
                setTimeout(() => location.reload(), 1200);
            } else {
                if (feedback) {
                    feedback.style.color = "#ef4444";
                    feedback.textContent = `❌ ${data.error || "Failed to save product"}`;
                }
            }
        } catch (err) {
            if (feedback) {
                feedback.style.color = "#ef4444";
                feedback.textContent = "❌ Connection error";
            }
        }
    });
}

// =========================================================================
// CREATE ADMIN USER FORM (ADMIN ONLY)
// =========================================================================
function initCreateUserForm() {
    const form = document.getElementById("createMasterUserForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const feedback = document.getElementById("createUserFeedback");

        const payload = {
            username: document.getElementById("newMasterUsername").value.trim(),
            password: document.getElementById("newMasterPassword").value,
            role: document.getElementById("newMasterRole").value,
            discord_id: document.getElementById("newMasterDiscordId").value.trim() || null
        };

        try {
            const res = await fetch("/api/admin/users", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok && data.status === "success") {
                if (feedback) {
                    feedback.style.color = "#10b981";
                    feedback.textContent = `✅ User '${payload.username}' created with role '${payload.role}'!`;
                }
                form.reset();
            } else {
                if (feedback) {
                    feedback.style.color = "#ef4444";
                    feedback.textContent = `❌ ${data.error || "Failed to create user"}`;
                }
            }
        } catch (err) {
            if (feedback) {
                feedback.style.color = "#ef4444";
                feedback.textContent = "❌ Connection error";
            }
        }
    });
}
