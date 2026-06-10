# ⚓ Discord Tournament Bot

A premium, fully-featured Discord tournament management bot built for the **TASK FORCE TRIDENT** esports organisation. 
Officiates events, synchronises schedules with Challonge brackets, records scores, tracks staff activity, and generates customized match event posters.

---

## 📑 Table of Contents

1. [Bot Overview](#-bot-overview)
2. [System Architecture](#%EF%B8%8F-system-architecture)
   - [Data Flow Diagram](#data-flow-diagram)
   - [Core Components](#core-components)
3. [Database Configuration (Supabase)](#-database-configuration-supabase)
4. [Command Reference](#-command-reference)
   - [System Commands](#-system-commands)
   - [Player Commands](#-player-commands)
   - [Event Management Commands](#-event-management-commands)
   - [Judge Commands](#-judge-commands)
   - [Admin Commands](#-admin-commands)
5. [Player Information System](#-player-information-system)
6. [Event Lifecycle](#-event-lifecycle)
7. [Environment Setup & Installation](#-environment-setup--installation)

---

## 🤖 Bot Overview

| Property | Details |
|---|---|
| Framework | `discord.py` (v2.x) with Slash Commands (`app_commands`) |
| Language | Python 3.10+ |
| Primary Database | **Supabase** (PostgreSQL) |
| Local Fallback | JSON flat-files (`guild_configs.json`, `tournaments.json`, `scheduled_events.json`) |
| APIs Integrated | Challonge API, Google Sheets (CSV lookup) |
| Image Engine | `Pillow (PIL)` with custom Font scaling & overlay engine |
| Accent Color | Navy Blue (`#1E3A5F`) |

---

## 🛠️ System Architecture

The bot is designed to be fully multi-server (multi-tenant), storing independent configurations, tournaments, and events for each Discord guild.

### Data Flow Diagram

```mermaid
graph TD
    A[Discord Client] -->|Slash Commands| B[Discord Bot - main.py]
    A -->|Button/Dropdown Interaction| B
    
    B -->|Fetch/Upsert Config| C[(Supabase Database)]
    B -->|Fetch/Upsert Config Fallback| D[(Local JSON Files)]
    
    B -->|Autocomplete / Update Match| E[Challonge REST API]
    B -->|Retrieve Captains / Players| F[Google Sheets CSV]
    B -->|Render Poster / Scale Fonts| G[Pillow Image Engine]
    
    B -->|Alerts & Reminders| H[Discord Guild Channels]
```

### Core Components

1. **Discord Command Listener (`main.py`):** Coordinates interactions, slash commands, views, and button clicks. Resolves context safety using task-local `ContextVar` parameters (`current_guild_id`) to load the correct server config.
2. **Supabase Client (`supabase-py`):** Acts as the primary backend database. Handles configurations (`GuildConfig` table) and tournament setups (`Tournaments` table).
3. **Local Persistence Engine:** Flat JSON files automatically cache database records locally, guaranteeing the bot boots even if Supabase is offline.
4. **Google Sheets Roster Integration:** Fetches captain mappings and player/team registration details dynamically from Google Sheets using unauthenticated CSV exports, keeping Discord commands fast and responsive.
5. **Challonge Integration:** Officiates bracket scores directly. Fetches open matches dynamically for command autocompletion and pushes match outcomes to the bracket.
6. **Poster Generator (`Pillow`):** Loads randomly selected background templates, resolves customized fonts (DS-Digital, Square One, Capture It), scales text sizes dynamically to fit names without clipping, and renders the match details.

---

## 🗄️ Database Configuration (Supabase)

The bot operates on five main tables in Supabase:

1. **`GuildConfig`:** Stores server configurations (rules channel, schedule channel, judge role, results channel, organization name).
2. **`Tournaments`:** Holds configurations for individual tournaments created in the guild.
3. **`Events`:** Records created matches. (Columns: `Created_By_ID` and `Created_By_Name` must be present).
4. **`JudgeAssignments`:** Logs judge and recorder claims and assignments.
5. **`Results`:** Saves finalized match scores, remarks, and screenshot attachment counts.
6. **`StaffStats`:** Increments match points for judges/recorders on the leaderboards.
7. **`Challonge_Uploads`:** Records Challonge score update success/failure histories.

---

## 📋 Command Reference

### ⚙️ System Commands
- `/help` — Displays interactive paginated guide with category filters.
- `/info` — Displays bot status, ping, and server information.
- `/staff-leaderboard` — Shows current leaderboards for Judges & Recorders.

### 🎮 Player Commands
- `/player_information` — Searches your configured Google Sheet for a player/captain and outputs their roster, IGNs, and Discord ID mentions.
- `/id-card` — Generates a customized graphic Clan ID Card for a player.
- `/maps` — Randomly rolls a map selection (3, 5, or 7 maps) from the map pool.
- `/choose` — Picks an item from a comma-separated list.
- `/time` — Generates a random match time slot within specific parameters.

### 🏆 Event Management Commands
- `/event-create` — Creates a match event, generates a poster with scaling font margins, logs the event to the database, and schedules pre-match reminders.
- `/event-edit` — Edits details of the active match (reschedule time, captains, round) in the current channel.
- `/event-delete` — Un-schedules and deletes a scheduled match.
- `/exchange` — Swaps a Judge or Recorder for an event.

### ⚖️ Judge Commands
- **Take Schedule** button — Claims the match in the `#schedule` channel.
- **Record** button — Claims the recorder slot for the match.
- `/reassign` — Resigns from an assigned match and notifies other judges.
- `/available_events` — Lists scheduled matches needing a judge.
- `/event-result` — Enters official match results, uploads screenshots, logs stats, and posts results.
- `/upload-score` — Uploads scores directly to Challonge bracket using an autocomplete match list. Takes exactly three parameters:
  - `winner` (Dropdown selection): Autocompleted list of active matches. If run inside a match ticket, it displays just the simple team/player names (e.g. `Carb-zir-nian` or `lets win for bundle`) by matching the channel topic `MatchID:XXXX`. Otherwise, it formats choices as `TeamName (vs OpponentName)`.
  - `winner_score` (Integer): Final score of the winner.
  - `loser_score` (Integer): Final score of the loser.

### 👑 Admin Commands
- `/settings add` — Set server-wide role mappings and branding parameters (Organization name, Sheet links, Bot name).
- `/settings edit` — Modify server-wide role mappings and branding parameters.
- `/settings show` — Displays a clean embed detailing all active server roles and configurations.
- `/settings clean` — Resets all configuration data, deletes guild database tables, and wipes local cache files.
- `/tournament add` — Registers a tournament configuration (name, challonge key, bracket link, sheet link, channels, categories, auto room setting).
- `/tournament edit` — Modifies an existing tournament config (bracket link, sheet link, channels, open/closed ticket categories, state: `pending`, `active`, `completed`).
- `/tournament delete` — Deletes tournament from database and local cache.
- `/tournament info` — Displays detailed channels, roles, and status of a tournament.
- `/tournament list` — Lists all tournaments registered for the server.
- `/auto_room run` — Manually triggers the automatic match room ticket creation sweep.
- `/auto_room stop` — Suspends the automatic match room loop for a tournament.
- `/auto_room toggle` — Toggles the automatic match room loop status.
- `/clear category` — Deletes all open/closed ticket channels in a specified category (Organizer only).
- `/clear cache` — Cleared Challonge bracket and sheet caches.
- `/registration` — Publish a Google Form registration embed with a direct button.
- `/publish-rules` — Write and publish tournament rules directly to guidelines.
- `/test_channels` — Run diagnostic check on bot permissions in configured channels.
- `/staff-update` — Manually update staff stats/points on the leaderboard.

---

## 🎮 Player Information System

The `/player_information` command searches your Google Sheet. Setup requires columns matching your format:
- **1 vs 1 Columns:** `Player Discord ID` | `Player Game Name` | `Player Game ID` | `Player Title` (Supports flexible match names like `Discord`, `UID`, `ID`, `IGN`).
- **Team Columns (2v2 - 5v5):** `Team Name` | `Captain Discord ID` | `Captain Game Name` | `Captain Game ID` | `Captain Title` | `Player 2 Discord ID` ... `Player 5 Title`

To configure links and formats:
Use `/settings add` or `/settings edit` with parameters `player_info_link` and `player_info_format`.

---

## 🔄 Event Lifecycle

1. **Create:** `/event-create` creates match → Renders poster banner → Logs to database → Posts schedule.
2. **Claim:** Judges/Recorders click buttons in the `#schedule` channel to assign themselves (notifies the match ticket via simple plain-text messages).
3. **Presence Ask (30m):** 30 minutes before the start time, the bot sends a simple presence confirmation embed to the ticket and alerts missing staff.
4. **Presence Check (20m):** 20 minutes before the start time, the bot checks staff presence. If staff has not confirmed, it locks confirmation and triggers replacement alerts in the schedule channel.
5. **Captains Reminder (10m):** 10 minutes before the start time, the bot sends the match player reminder to captains.
6. **Finalize:** Judge runs `/event-result` to log scores, upload screenshots, and post results to the results channel (using a compact embed layout).
7. **Sync:** Results upload to Challonge via `/upload-score` (the winner option shows clean team names, automatically filtered if run inside the ticket channel).

---

## 🔧 Environment Setup & Installation

### Local Setup
1. Clone the repository.
2. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file containing:
   ```env
   DISCORD_TOKEN=your_token
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_service_role_key
   ```
4. Run the bot:
   ```bash
   python main.py
   ```

---

## 👥 Credits & Developer Info
* **Developer:** Siva Subramaniam
* **Discord Username:** Hokage

---

## 🗓️ Version History & Changelog

### **v1.3.0 (Latest Update)**
* **Staff Timings Shift**: Realigned pre-match staff confirmation to a 30-minute presence check-in, 20-minute presence validation/replacement trigger, and 10-minute player match reminder flow.
* **Simplified Claim Messages**: Replaced initial claim embeds in tickets with plain-text `{mention} assigned as **role** {emoji}` alerts. Confirmation buttons are now exclusively posted at the 30-minute reminder mark.
* **Sleeker Autocomplete**: Restructured `/upload-score` autocompletes to show clean team/player names. If executed inside a match ticket, it automatically reads the channel topic's `MatchID:XXXX` and shows only the relevant two competing teams.
* **Tighter Results Layout**: Removed redundant vertical blank space fields from the `/event-result` embed.
* **Detailed Logs**: Log presence confirmations, staff replacements, and score uploads directly to the Discord bot logs and tournament-specific Challonge logs channels.

### **v1.2.0**
* **Database Alignment**: Re-arranged and cleaned up `GuildConfig` and `Tournaments` database column header orders in Supabase to match custom sheet sequences exactly.
* **Branding Clean**: Removed `Tournament Name`, `Player Info Link`, and `Player Info Format` fields from the `/settings show` embed presentation.
* **Google Sheet Tab `gid` Support**: Updated `/config_player_information` and `/player_information` commands to extract the sheet tab ID (`gid=`) from the URL. The bot now syncs the exact configured sheet sub-tab instead of defaulting to the first tab.
* **Railway Crash Fix**: Added the missing `supabase` package dependency to `requirements.txt` to prevent boot crashes on deployment.

### **v1.1.0**
* **Supabase Integration**: Migrated guild configs and tournament settings storage to Supabase PostgreSQL backend.
* **Multi-Guild Isolation**: Added workspace isolation supporting config/attendance channels across multiple Discord servers.
* **Challonge logs**: Added tracking database tables for bracket upload stats.

### **v1.0.0**
* **Initial Release**: Basic event life-cycle management, Claim Schedule / Record claims, PIL poster generation, and local JSON config caching.

---

*Built for **TASK FORCE TRIDENT** · Powered by discord.py and Supabase*
