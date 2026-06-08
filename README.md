# ⚓ TASK FORCE TRIDENT — Discord Bot

> A fully-featured Discord tournament management bot built for **TASK FORCE TRIDENT** esports organisation.  
> Handles event scheduling, judge coordination, result recording, player information lookup, and more.

---

## 📑 Table of Contents

1. [Bot Overview](#-bot-overview)
2. [Architecture & File Structure](#-architecture--file-structure)
3. [Configuration System](#-configuration-system)
4. [Command Reference](#-command-reference)
   - [System Commands](#%EF%B8%8F-system-commands)
   - [Event Management Commands](#-event-management-commands)
   - [Judge Commands](#%EF%B8%8F-judge-commands)
   - [Player Information Commands](#-player-information-commands)
   - [Utility Commands](#%EF%B8%8F-utility-commands)
5. [Player Information System](#-player-information-system)
   - [1 vs 1 Format](#1-vs-1-format)
   - [2 vs 2 – 5 vs 5 Format](#2-vs-2--5-vs-5-format)
   - [Required Google Sheet Columns](#required-google-sheet-columns)
6. [Event Lifecycle](#-event-lifecycle)
7. [Permission Levels](#-permission-levels)
8. [Data Persistence](#-data-persistence)
9. [Environment Variables](#-environment-variables)
10. [Quick Start](#-quick-start)
11. [Troubleshooting](#-troubleshooting)

---

## 🤖 Bot Overview

| Property | Details |
|---|---|
| Framework | `discord.py` (v2.x) with slash commands (`app_commands`) |
| Language | Python 3.10+ |
| Storage | JSON flat-files + optional Firebase Firestore |
| External APIs | Google Sheets (CSV export), Challonge API, SheetDB |
| Branding | TASK FORCE TRIDENT — Navy Blue (`#1E3A5F`) |

---

## 🗂 Architecture & File Structure

```
TASK FORCE TRIDENT/
├── app.py                    # Main bot file — all commands & logic
├── main.py                   # Entry point (imports & runs app.py)
├── config/
│   └── config.py             # Config loader helper (role IDs, channel IDs)
├── cogs/
│   └── utilities.py          # Misc. utility cog (if separated)
├── utils/                    # Shared utility helpers
├── Templates/                # Image card / banner templates
├── Fonts/                    # Custom fonts for image rendering
├── .env                      # Environment variables (token, secrets)
├── env.example               # .env template for new deployments
├── bot_config.json           # Runtime config saved by /config_* commands
├── scheduled_events.json     # Persisted event schedule data
├── tournament_rules.json     # Published rules content
├── staff_stats.json          # Judge & recorder leaderboard data
├── requirements.txt          # Python dependencies
├── Procfile                  # Deployment start command (Railway / Heroku)
├── nixpacks.toml             # Railway build config
├── README.md                 # This file
├── README-Docker.md          # Docker deployment guide
└── README-Railway.md         # Railway deployment guide
```

### Core Sections inside `app.py`

| Section | Lines (approx.) | Purpose |
|---|---|---|
| Imports & Firebase Setup | 1–50 | Dependencies, Firebase init |
| Default Config Constants | 51–92 | Hard-coded channel/role IDs, branding |
| `load_config / save_config` | 94–155 | Read/write `bot_config.json` or Firebase |
| SheetDB Integration | 235–265 | POST match results to Google Sheets |
| Challonge API Helpers | 265–325 | Fetch open matches, update results |
| Google Sheet Captains | 326–385 | Read captain→Discord ID map from Sheet |
| Rule Management System | 386–510 | Store & publish tournament rules |
| COMMAND_DATA + Help system | 508–800 | Help embed builder + button navigation |
| Event Management Commands | ~850–2500 | `/event-create`, `/event-edit`, `/event-result`, etc. |
| Judge & Staff Commands | ~2500–3300 | Take schedule, reassign, leaderboard |
| Auto-ticket System | ~3300–3920 | Automatically create match channels |
| Map & Utility Commands | ~3920–4075 | `/maps`, `/choose`, `/time` |
| Rules Publishing | ~4075–4125 | `/publish-rules`, `RulesModal` |
| **Player Information System** | **4264–4475** | **`/config_player_info`, `/player_information`** |
| Bot startup | 4475+ | Token loading, `bot.run()` |

---

## ⚙️ Configuration System

The bot reads from two sources (Firebase takes priority over JSON):

```
Firebase Firestore  →  Collection: "Bots"  →  Doc: "Valorant_Vanguard_Esports"
                       → Sub-collection: "Config" → Doc: "bot_config"

Local fallback      →  bot_config.json  (created automatically on first /config run)
```

Config fields stored:

| Key | Description |
|---|---|
| `channel_ids` | Map of channel names → Discord channel IDs |
| `role_ids` | Map of role names → Discord role IDs |
| `organization_name` | Display name (default: `TASK FORCE TRIDENT`) |
| `tournament_system_name` | Full system name for embeds |
| `bracket_link` | Challonge bracket URL |
| `bracket_api_key` | Challonge API key |
| `google_sheet_link` | Google Sheet for captain/team map |
| `current_tournament_name` | Active tournament label |
| `player_info_link` | Google Sheet link for player info |
| `player_info_format` | Format: `1 vs 1` / `2 vs 2` … `5 vs 5` |

---

## 📋 Command Reference

### ⚙️ System Commands

| Command | Permission | Description |
|---|---|---|
| `/help` | Everyone | Shows paginated help with category buttons |

---

### 🏆 Event Management Commands

| Command | Permission | Description |
|---|---|---|
| `/event-create` | Organizer / Helper | Create a tournament event with schedule, teams, round, group |
| `/event-edit` | Organizer / Helper | Edit an existing scheduled event |
| `/event-result` | Organizer / Judge | Record match result with winner, score, round, group, screenshots |
| `/event-delete` | Organizer / Helper | Delete a scheduled event |
| `/available_events` | Organizer / Helper / Judge | List all events with no judge assigned |
| `/exchange` | Organizer / Helper | Swap Judge or Recorder on an event in current channel |
| `/staff-update` | Head Organizer | Manually adjust staff leaderboard counts |

**Event Create Parameters:**
```
team_1_captain  — @mention of captain / player 1
team_2_captain  — @mention of captain / player 2
hour            — 0–23 (UTC)
minute          — 0–59
date            — 1–31
month           — 1–12
round           — R1–R10 | Qualifier | Semi Final | 3rd Place | Final
tournament      — Tournament name string
group           — (optional) Group A–J | Winner | Loser
```

---

### ⚖️ Judge Commands

| Command / Action | Permission | Description |
|---|---|---|
| **Take Schedule** button | Judge / Organizer | Click button on event post to self-assign as judge |
| `/unassigned_events` | Judge / Organizer | Drop an event you previously took |
| `/available_events` | Judge / Organizer | See unassigned matches |
| `/event-result` | Judge / Organizer | Submit official match result |

**Automatic Judge Reminders:**
- **20 minutes** before a match: bot pings if no judge is assigned  
- **10 minutes** before a match: secondary reminder sent to schedule channel  
- Take Schedule button is **disabled** once the event starts

---

### 🎮 Player Information Commands

| Command | Permission | Description |
|---|---|---|
| `/config_player_info` | Bot Owner | Set the Google Sheet link and match format |
| `/player_information` | Everyone | Lookup a player or captain's info from the sheet |

---

### 🛠️ Utility Commands

| Command | Permission | Description |
|---|---|---|
| `/time` | Everyone | Generate a random match time (12:00–17:59 UTC) |
| `/choose` | Everyone | Randomly pick from a comma-separated list |
| `/maps` | Everyone | Randomly select 3, 5, or 7 maps from the pool |
| `/publish-rules` | Organizer / Judge | Open modal to write & publish rules to rules channel |
| `/test_channels` | Bot Owner / Organizer | Verify bot can access all configured channels |

---

## 🎮 Player Information System

The `/player_information` command fetches structured data from a publicly shared Google Sheet.  
The sheet format (and therefore which columns are read) depends on the **match format** set via `/config_player_info`.

---

### 1 vs 1 Format

Used when the tournament is solo players facing each other.

**Sheet lookup:** Searches all cells for the user's **Discord ID** or `<@mention>`.

**Fields displayed in the embed:**

| # | Field Name (exact column header required) | Description |
|---|---|---|
| 1 | `Player Discord ID` | The player's Discord user ID (auto-formatted as `<@ID>`) |
| 2 | `Player Game Name` | In-game username / IGN |
| 3 | `Player Game ID` | In-game UID / tag |
| 4 | `Player Title` | Player's in-game title or rank |

---

### 2 vs 2 – 5 vs 5 Format

Used for team-based tournaments. The number of player slots displayed scales with the format chosen.

**Sheet lookup:** Searches all cells for the captain's **Discord ID** or `<@mention>`.

**Fields displayed in the embed:**

#### Captain (Slot 1 — always shown):

| # | Field Name | Description |
|---|---|---|
| 1 | `Team Name` | Official team/clan name |
| 2 | `Captain Discord ID` | Captain's Discord ID (auto-formatted as `<@ID>`) |
| 3 | `Captain Game Name` | Captain's IGN |
| 4 | `Captain Game ID` | Captain's in-game UID |
| 5 | `Captain Title` | Captain's in-game title |

#### Player 2 (shown for 2v2 and above):

| # | Field Name | Description |
|---|---|---|
| 6 | `Player 2 Discord ID` | Player 2's Discord ID |
| 7 | `Player 2 Game Name` | Player 2's IGN |
| 8 | `Player 2 Game ID` | Player 2's in-game UID |
| 9 | `Player 2 Title` | Player 2's in-game title |

#### Player 3 (shown for 3v3 and above):

| # | Field Name |
|---|---|
| 10 | `Player 3 Discord ID` |
| 11 | `Player 3 Game Name` |
| 12 | `Player 3 Game ID` |
| 13 | `Player 3 Title` |

#### Player 4 (shown for 4v4 and above), Player 5 (shown for 5v5):

> Same pattern — `Player 4 Discord ID`, `Player 4 Game Name`, `Player 4 Game ID`, `Player 4 Title`, and same for Player 5.

---

### Required Google Sheet Columns

Your Google Sheet **must use these exact column headers** (case-insensitive, leading/trailing spaces ignored):

#### For 1 vs 1:

```
Player Discord ID | Player Game Name | Player Game ID | Player Title
```

#### For 2 vs 2 – 5 vs 5:

```
Team Name | Captain Discord ID | Captain Game Name | Captain Game ID | Captain Title |
Player 2 Discord ID | Player 2 Game Name | Player 2 Game ID | Player 2 Title |
Player 3 Discord ID | Player 3 Game Name | Player 3 Game ID | Player 3 Title |
Player 4 Discord ID | Player 4 Game Name | Player 4 Game ID | Player 4 Title |
Player 5 Discord ID | Player 5 Game Name | Player 5 Game ID | Player 5 Title
```

> ⚠️ Only include columns up to your team size. Extra columns are ignored.

**Sheet must be shared as "Anyone with the link can view" for the bot to read it.**

#### How to set up:

```
/config_player_info link:<your_google_sheet_url> format:<1 vs 1 | 2 vs 2 | ... | 5 vs 5>
```

---

## 🔄 Event Lifecycle

```
/event-create  →  Event posted in #take-schedule channel
                  ↓
               [Take Schedule button available]
                  ↓
               Judge clicks button → Assigned & button disabled
                  ↓
               20-min pre-match ping (if no judge assigned)
               10-min reminder ping
                  ↓
               Match begins → Take Schedule button permanently disabled
                  ↓
               /event-result submitted by judge
                  ↓
               Result posted in #results channel
               SheetDB row added to Google Sheets
               Event cleaned up automatically
```

---

## 🔐 Permission Levels

| Level | Roles | Access |
|---|---|---|
| **Bot Owner** | Hard-coded Owner ID | All commands + `/config_*` |
| **Organizer** | Head Organizer role | All management commands |
| **Helper** | Helper Team / Head Helper | Event creation, editing, deletion |
| **Judge** | Judge role | Take schedule, submit results |
| **Recorder** | Recorder role | Limited event access |
| **Member** | Everyone else | `/help`, `/time`, `/choose`, `/maps`, `/player_information` |

---

## 💾 Data Persistence

| File | Contents |
|---|---|
| `bot_config.json` | All configuration set via slash commands |
| `scheduled_events.json` | Active event schedule (datetime, teams, judge) |
| `tournament_rules.json` | Published rules content + version history |
| `staff_stats.json` | Judge/recorder match count leaderboard |

All data is auto-saved after every write operation. On restart, all files are reloaded automatically.

---

## 🔧 Environment Variables

Create a `.env` file (see `env.example`):

```env
DISCORD_TOKEN=your_discord_bot_token_here
```

Optional (for Firebase):
```env
# Place firebase_credentials.json in project root
# Firebase is used automatically if the file exists
```

---

## 🚀 Quick Start

### Local Development

```bash
# 1. Clone the repo
git clone <repo_url>
cd "TASK FORCE TRIDENT"

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env file
cp env.example .env
# → Add your DISCORD_TOKEN

# 4. Run the bot
python main.py
```

### Docker

```bash
docker build -t tft-bot .
docker run --env-file .env tft-bot
# See README-Docker.md for full details
```

### Railway Deployment

See [`README-Railway.md`](README-Railway.md) for step-by-step Railway deployment.

---

## 🐛 Troubleshooting

| Issue | Fix |
|---|---|
| Bot not responding | Check `DISCORD_TOKEN` in `.env`, verify bot is invited with correct permissions |
| Commands not showing | Restart bot (commands sync on startup via `on_ready`) |
| Player info not found | Ensure the Google Sheet is public, column names match exactly, and the Discord ID is in the sheet |
| Judge take-schedule fails | Verify the Judge role ID in config matches your server's role |
| Firebase errors | Check `firebase_credentials.json` exists in project root; bot falls back to JSON if missing |
| SheetDB not posting | Verify `SHEETDB_API_URL` in `app.py` matches your SheetDB endpoint |

---

## 📜 Version History

### v3.0.0 (Current)
- Structured Player Information system (1v1 and team formats)
- Exact field mapping: Player Discord ID, Game Name, Game ID, Title
- Team format support: Team Name + Captain + Player 2–5 slots
- Discord ID auto-formatted as `<@mention>` in embeds
- `/config_player_info` for owner-only sheet setup
- Auto-disabled Take Schedule button on match start

### v2.0.0
- Group stage support (Group A–J, Winner, Loser brackets)
- Staff leaderboard with judge/recorder split tracking
- SheetDB integration for result logging
- Challonge API integration
- Auto-ticket channel creation for open matches

### v1.0.0
- Basic event creation and management
- Judge assignment system
- Discord slash commands
- Simple embed handling

---

*Built for **TASK FORCE TRIDENT** · Powered by discord.py*
