# 🏆 Tournament Bot — Complete Command Guidelines & Operator Manual

> **Welcome to the Tournament Bot Documentation.**  
> This guide provides a full, copy-paste-ready reference for Notion. It covers role permissions, workflows, and all slash & prefix commands categorized by operational area.

---

## 📑 Quick Navigation

- [👑 1. Permission Hierarchy](#1-permission-hierarchy)
- [⚙️ 2. Server & Bot Configuration (`/settings`)](#2-server--bot-configuration-settings)
- [🏆 3. Tournament Management (`/tournament`)](#3-tournament-management-tournament)
- [🎫 4. Automatic Room Creation (`/auto_room`)](#4-automatic-room-creation-auto_room)
- [🎮 5. Player & Roster System (`/player`, `/id-card`)](#5-player--roster-system-player-id-card)
- [📅 6. Match & Event Scheduling (`/event`)](#6-match--event-scheduling-event)
- [⏰ 7. Round Deadlines (`/deadline`)](#7-round-deadlines-deadline)
- [⚖️ 8. Staff & Match Officiating (`/staff`, `/event-result`)](#8-staff--match-officiating-staff-event-result)
- [🎥 9. VOD & Recording Links (`/link`)](#9-vod--recording-links-link)
- [📜 10. Match Room Tickets & Transcripts (`$close`, `$reopen`)](#10-match-room-tickets--transcripts-close-reopen)
- [🛠️ 11. Server Moderation & Utilities (`/channel`, `/purge`, etc.)](#11-server-moderation--utilities-channel-purge-etc)
- [🔄 12. Complete Match Day Lifecycle](#12-complete-match-day-lifecycle)

---

## 1. Permission Hierarchy

The bot enforces role-based access control. Configure role IDs using `/settings add` or `/settings edit`.

| Role Level | Required Server Role / Position | Permitted Scope |
|---|---|---|
| **Bot Owner / Administrator** | Discord Server Owner / Administrator | Unrestricted access across all commands, diagnostics, and wipes. |
| **Head Organizer** | `Admin_Role_ID` / `Organizer_Role_ID` | Tournament lifecycle, settings, auto-rooms, rule publishing, stats adjustments. |
| **Helper Team** | `Helper_Role_ID` | Staff assignment exchanges, channel management, match updates. |
| **Judge** | `Judge_Role_ID` | Claiming matches, submitting official scores/screenshots, resigning via `/reassign`. |
| **Recorder** | `Recorder_Role_ID` | Claiming recording slots, adding VOD/match video links. |
| **Players & Public** | `Players_Role_ID` / `@everyone` | Roster lookup (`/player_information`), ID cards, maps roll, bracket viewing. |

---

## 2. Server & Bot Configuration (`/settings`)

Use these commands during initial server onboarding or when updating server branding, bot channels, and staff roles.

### `/settings show`
- **Description:** Displays an embed detailing all active role IDs, channel mappings, and organization branding for the server.
- **Permission:** Head Organizer / Administrator
- **Parameters:** *None*

### `/settings add`
- **Description:** Configures server-wide staff role IDs, log channels, organization name, and default sheet links.
- **Permission:** Head Organizer / Administrator
- **Parameters:**
  - `head_organizer_role` *(Role, Optional)*: Role ID for Head Organizers.
  - `organizer_role` *(Role, Optional)*: Role ID for Organizers.
  - `helper_role` *(Role, Optional)*: Role ID for Helper Team.
  - `judge_role` *(Role, Optional)*: Role ID for Judges.
  - `recorder_role` *(Role, Optional)*: Role ID for Recorders.
  - `staff_role` *(Role, Optional)*: Master Staff role.
  - `players_role` *(Role, Optional)*: Participant / Players role.
  - `challonge_role` *(Role, Optional)*: Role permitted to sync Challonge scores.
  - `organization_name` *(String, Optional)*: Name displayed on posters and embed footers.
  - `bot_logs_channel` *(Channel, Optional)*: Channel for audit and bot operational logs.
  - `take_schedule_channel` *(Channel, Optional)*: Channel where match schedule claim posts are sent.
  - `results_channel` *(Channel, Optional)*: Channel where verified match results are published.

### `/settings edit`
- **Description:** Selectively updates specific configuration fields without re-entering all settings.
- **Permission:** Head Organizer / Administrator

### `/settings clean`
- **Description:** ⚠️ **Danger Zone**: Resets all server configuration data, wipes cached settings, and clears tournament associations.
- **Permission:** Bot Owner / Administrator

### `/test_channels`
- **Description:** Performs diagnostic checks verifying the bot's permissions (`Send Messages`, `Embed Links`, `Attach Files`, `Manage Channels`) in all configured channels.
- **Permission:** Head Organizer / Administrator

---

## 3. Tournament Management (`/tournament`)

Manage individual tournaments. The bot supports multiple simultaneous tournaments on a single Discord server.

### `/tournament add`
- **Description:** Registers a new tournament with its dedicated channels, categories, and bracket URLs.
- **Permission:** Head Organizer / Administrator
- **Key Parameters:**
  - `name` *(String, Required)*: Unique name or ID for the tournament.
  - `game` *(String, Required)*: Game title (e.g., `Valorant`, `Mobile Legends`, `PUBG Mobile`).
  - `key` *(String, Optional)*: Challonge tournament URL subdomain or identifier.
  - `challonge_bracket_link` *(String, Optional)*: Direct public URL to Challonge bracket.
  - `captains_sheet_link` *(String, Optional)*: Google Sheet CSV link containing captain Discord IDs and team names.
  - `schedule_channel` *(Channel, Optional)*: Tournament-specific `#schedule` channel.
  - `result_channel` *(Channel, Optional)*: Tournament-specific `#results` channel.
  - `attendance_channel` *(Channel, Optional)*: Channel for staff attendance records.
  - `transcript_channel` *(Channel, Optional)*: Channel where closed match ticket HTML transcripts are archived.
  - `open_category_1` to `open_category_4` *(Category, Optional)*: Discord categories where match room channels will be created.
  - `closed_category_1` & `closed_category_2` *(Category, Optional)*: Categories where closed match tickets are moved upon completion.

### `/tournament edit`
- **Description:** Updates channels, links, or state (`pending`, `active`, `completed`) for an existing tournament.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `tournament` *(Autocomplete, Required)* + any settings to update.

### `/tournament list`
- **Description:** Lists all registered tournaments in the guild, displaying their current status, game, and bracket links.
- **Permission:** Everyone

### `/tournament info`
- **Description:** Shows configuration details, category assignments, and channel bindings for a tournament.
- **Permission:** Everyone
- **Parameters:** `tournament` *(Autocomplete, Optional)*

### `/tournament delete`
- **Description:** Permanently deletes a tournament configuration, its scheduled deadlines, and bracket associations.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `tournament` *(Autocomplete, Required)*

---

## 4. Automatic Room Creation (`/auto_room`)

Automates match room ticket channel creation by monitoring open matches from Challonge and assigning captain permissions.

### `/auto_room start`
- **Description:** Enables automatic room creation for a tournament and launches the 5-minute background polling sweep.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `tournament` *(Autocomplete, Optional)*

### `/auto_room stop`
- **Description:** Disables automatic room creation and stops background polling for a tournament.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `tournament` *(Autocomplete, Optional)*

### `/auto_room toggle`
- **Description:** Toggles automatic room creation status on or off, with an optional explicit `enabled` parameter.
- **Permission:** Head Organizer / Administrator
- **Parameters:**
  - `tournament` *(Autocomplete, Optional)*
  - `enabled` *(Boolean, Optional)*: `True` to turn ON, `False` to turn OFF.

### `/auto_room run`
- **Description:** Forces an immediate manual sweep of the Challonge bracket to create rooms for any unhandled open matches.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `tournament` *(Autocomplete, Optional)*

### `/auto_room status`
- **Description:** Displays the auto room status, open category capacities, and last sweep time for a tournament.
- **Permission:** Everyone
- **Parameters:** `tournament` *(Autocomplete, Optional)*

---

## 5. Player & Roster System (`/player`, `/id-card`)

Handles participant registration, roster verification, and player profile lookup via Google Sheets.

### `/player_information`
- **Description:** Searches the configured tournament Google Sheet for a player or captain and formats their roster cleanly.
- **Permission:** Everyone
- **Parameters:** `query` *(String, Required)*: Discord ID, mention, or In-Game Name.

### `/config_player_information`
- **Description:** Configures the Google Sheet link and sets the `#participants` channel where roster cards are published.
- **Permission:** Head Organizer / Administrator
- **Parameters:**
  - `sheet_link` *(String, Required)*: Google Sheet unauthenticated CSV export link.
  - `participant_channel` *(Channel, Required)*: Target channel to post verified player cards.
  - `format_type` *(Choice, Required)*: `1v1` or `Team (2v2 - 5v5)`.

### `/player edit`
- **Description:** Edits a participant's details in the posted roster message, `players.json` / `teams.json`, and Supabase tables.
- **Permission:** Head Organizer / Administrator
- **Parameters:**
  - `user` *(User, Required)*: Player or Captain to update.
  - `field` *(Choice, Required)*: `Game Name (IGN)`, `Game ID (UID)`, `Title`, or `Team Name`.
  - `new_value` *(String, Required)*: New value to set.

### `/id-card`
- **Description:** Generates a high-resolution graphic Player ID Card with team badge, avatar, and IGN.
- **Permission:** Everyone
- **Parameters:**
  - `ign` *(String, Required)*: In-game name.
  - `uid` *(String, Required)*: In-game character/account ID.
  - `team_name` *(String, Optional)*: Clan or team name.

### `/maps`
- **Description:** Rolls a random selection of competitive maps from the official map pool.
- **Permission:** Everyone
- **Parameters:** `amount` *(Choice, Optional)*: `3 Maps (BO3)`, `5 Maps (BO5)`, or `7 Maps (BO7)`.

---

## 6. Match & Event Scheduling (`/event`)

Controls match announcements, visual poster generation, and pre-match reminders.

### `/event-create`
- **Description:** Creates an official match schedule post, generates an event poster with team badges, logs to Supabase `Matches`, and posts to `#schedule` with interactive claim buttons.
- **Permission:** Head Organizer / Helper Team
- **Key Parameters:**
  - `tournament` *(Autocomplete, Required)*
  - `team1_captain` *(User, Required)*
  - `team2_captain` *(User, Required)*
  - `date` *(String, Required)*: Format `DD/MM` (e.g. `25/10`).
  - `time` *(String, Required)*: Time in UTC, e.g. `18:00 UTC`.
  - `round` *(String, Required)*: e.g. `Round 1`, `Quarter-Finals`, `Finals`.
  - `group` *(String, Optional)*: e.g. `Group A`.
  - `channel` *(Channel, Optional)*: The private match room channel.

### `/event-edit`
- **Description:** Edits details of an existing match (reschedule date/time, captains, round) in the current match room.
- **Permission:** Head Organizer / Helper Team

### `/event-delete`
- **Description:** Cancels a scheduled match, clears its reminders, and removes it from the active schedule.
- **Permission:** Head Organizer / Administrator

---

## 7. Round Deadlines (`/deadline`)

Announces match completion deadlines with dynamic countdowns and automated reminder pings.

### `/deadline add`
- **Description:** Adds and announces a round deadline in `#deadlines` with `<t:TIMESTAMP:F>` and `<t:TIMESTAMP:R>` relative countdowns. Automatically schedules reminder pings (24h before & on deadline day at 06:00 UTC).
- **Permission:** Head Organizer / Administrator
- **Parameters:**
  - `round` *(String, Required)*: Round name (e.g. `Round 2`).
  - `date` *(String, Required)*: Format `DD/MM/YYYY`.
  - `time` *(String, Required)*: Time in UTC (e.g. `20:00 UTC`).
  - `tournament` *(Autocomplete, Optional)*
  - `note` *(String, Optional)*: Special rules or notes for players.

### `/deadline edit`
- **Description:** Modifies an existing deadline's timestamp or notes and updates the announcement message.
- **Permission:** Head Organizer / Administrator

### `/deadline delete`
- **Description:** Deletes a scheduled deadline from `scheduled_deadlines.json` and Supabase `Deadlines`, canceling reminders.
- **Permission:** Head Organizer / Administrator

### `/deadline list`
- **Description:** Lists all active tournament deadlines with live Discord relative countdowns.
- **Permission:** Everyone

---

## 8. Staff & Match Officiating (`/staff`, `/event-result`)

Handles match claiming, referee check-ins, result verification, and staff performance leaderboards.

### In-Channel Claim Buttons
- **`Take Schedule` (Button)**: Claim the Judge position for a match directly from `#schedule`.
- **`Record` (Button)**: Claim the Recorder position for a match.
- **`Confirm Presence` (Button)**: Appears 30 minutes before match time in the ticket. Staff must click to confirm availability; unconfirmed staff are automatically unassigned 20 minutes before match time.

### `/available_events` (or `/unassigned`)
- **Description:** Lists all scheduled matches that currently lack a Judge, with interactive claim dropdowns.
- **Permission:** Judges / Staff / Organizers

### `/reassign`
- **Description:** Allows an assigned Judge or Recorder to resign from an upcoming match, notifying other staff to claim it.
- **Permission:** Judge / Recorder / Staff

### `/exchange`
- **Description:** Swaps an existing Judge or Recorder with a new staff member and updates channel permissions.
- **Permission:** Head Organizer / Helper Team
- **Parameters:** `role`, `old_user`, `new_user`.

### `/event-result`
- **Description:** Official score entry command. Prompts for winning team, scores, screenshot proof, and remarks. Awards staff stats points and posts verified results to `#results`.
- **Permission:** Assigned Judge / Head Organizer
- **Parameters:**
  - `winner` *(Choice, Required)*: `Team 1` or `Team 2`.
  - `winner_score` *(Integer, Required)*
  - `loser_score` *(Integer, Required)*
  - `screenshot1` to `screenshot3` *(Attachments, Optional)*: Match scoreboard proof.
  - `remarks` *(String, Optional)*: Overtime notes, penalties, or comments.
  - `disqualified` *(Boolean, Optional)*: Mark if a team was DQ'd.

### `/upload-score`
- **Description:** Pushes verified match scores directly to Challonge bracket via API with autocomplete match selection.
- **Permission:** Challonge Role / Head Organizer

### `/staff-leaderboard`
- **Description:** Displays the server staff leaderboard ranking Judges, Recorders, and Dual-Role staff by match count.
- **Permission:** Everyone

### `/staff work`
- **Description:** Displays individual match history and performance statistics for a specific staff member.
- **Permission:** Everyone
- **Parameters:** `member` *(User, Required)*, `tournament` *(Autocomplete, Optional)*.

### `/staff-update`
- **Description:** Manually adds, subtracts, or sets match points on the staff leaderboard.
- **Permission:** Head Organizer / Administrator
- **Parameters:** `staff_member`, `role`, `action` (`add`, `subtract`, `set`), `amount`.

---

## 9. VOD & Recording Links (`/link`)

Attaches and updates official stream/recording links on match records and results embeds.

### `/link add`
- **Description:** Adds recording links to a match. Supports up to 5 multi-link inputs (`link1` to `link5`), selects link category (`General Recording`, `Recorder VOD`, `Judge VOD`), awards recorder points, and edits the results channel embed live.
- **Permission:** Recorders / Judges / Staff
- **Parameters:**
  - `match` *(Autocomplete, Required)*
  - `link_type` *(Choice, Required)*: `General Recording`, `Recorder VOD`, or `Judge VOD`.
  - `link1` *(String, Required)*: Video/stream URL.
  - `link2` to `link5` *(String, Optional)*: Additional VOD parts.

### `/link edit`
- **Description:** Modifies an existing recording link URL for a match.
- **Permission:** Staff / Organizers

### `/link delete`
- **Description:** Removes a link or all links from a match record.
- **Permission:** Head Organizer / Administrator

### `/link missing`
- **Description:** Shows a paginated list of completed matches that have not yet uploaded a recording link.
- **Permission:** Staff / Organizers

---

## 10. Match Room Tickets & Transcripts (`$close`, `$reopen`)

Commands used inside private match rooms for channel state management and archiving.

### `$close` or `/close`
- **Description:** Closes the current match channel and executes the automated archival pipeline:
  1. Generates an interactive **Discord Dark Theme HTML Transcript (`.html`)** with **Base64 embedded images** (images never expire).
  2. Generates a clean **Plain-Text Transcript (`.txt`)**.
  3. Sends both transcript files to the ticket.
  4. Automatically uploads transcripts to the tournament `#transcripts` channel.
  5. Moves the channel to the configured `Closed_Category_ID`.
- **Permission:** Head Organizer / Helper / Assigned Judge

### `$reopen` or `/reopen`
- **Description:** Reopens an archived match ticket, removes closed status prefixes, and moves it back to active categories with restored captain permissions.
- **Permission:** Head Organizer / Helper

### `$delete` or `/delete_room`
- **Description:** Permanently deletes the current match ticket channel.
- **Permission:** Head Organizer / Administrator

### Prefix Status Quick-Commands
Inside any match room, organizers can use quick prefixes to update ticket titles:
- `?sh` ➔ Prepends `🟢-` (Scheduled)
- `?dq` ➔ Prepends `🔴-` (Disqualified)
- `?dd` ➔ Prepends `✅-` (Deadline Completed)
- `?ho` ➔ Prepends `🟡-` (On Hold)

---

## 11. Server Moderation & Utilities (`/channel`, `/purge`, etc.)

Helpful day-to-day administrative and moderation commands.

| Command | Usage | Description | Permission |
|---|---|---|---|
| `/channel lock` | `/channel lock [channel]` | Locks a channel from `@everyone` speaking. | Helper / Organizer |
| `/channel unlock` | `/channel unlock [channel]` | Restores speaking permissions for `@everyone`. | Helper / Organizer |
| `/channel add` | `/channel add <member_or_role>` | Grants a user or role view/talk access to the current channel. | Helper / Organizer |
| `/purge all` | `/purge all <amount>` | Bulk deletes messages in current channel (max 100). | Organizer / Admin |
| `/purge word` | `/purge word <word> <amount>` | Deletes messages containing a specific keyword. | Organizer / Admin |
| `/clear category` | `/clear category <category>` | Bulk deletes all ticket channels within a designated category. | Organizer / Admin |
| `/clear cache` | `/clear cache [type]` | Clears Challonge and Google Sheet memory caches. | Organizer / Admin |
| `/timeout add` | `/timeout add <user> <duration>` | Mutes a user for `5m`, `1h`, `1d`, `7d`, or `28d`. | Helper / Organizer |
| `/timeout remove` | `/timeout remove <user>` | Removes timeout from a user. | Helper / Organizer |
| `/assign_role` | `/assign_role <tournament> <role>` | Bulk assigns a role to all players from the Google Sheet roster. | Organizer / Admin |
| `/role remove all`| `/role remove all <role>` | Bulk removes a role from all server members with confirmation. | Organizer / Admin |
| `/categorymonitor`| `/categorymonitor set/view/remove` | Monitors channel capacity in categories to prevent hitting Discord's 50-channel limit. | Organizer / Admin |
| `/server info` | `/server info` | Displays detailed server statistics, member counts, and roles. | Everyone |

---

## 12. Complete Match Day Lifecycle

Here is the standard operating lifecycle from match announcement to post-match archival:

```
[1] /auto_room start OR /auto_room run
    └── Bot detects open match from Challonge → creates private room channel with both captains.

[2] /event-create
    └── Organizers schedule the match → Bot renders poster → Posts to #schedule with claim buttons.

[3] Staff Claiming
    └── Judges and Recorders click "Take Schedule" and "Record" buttons on the schedule post.

[4] Match Day Check-In (Automated)
    ├── T-30 Min: Bot sends "Confirm Presence" check to match ticket.
    ├── T-20 Min: Unconfirmed staff are replaced automatically; alert sent to #schedule.
    └── T-10 Min: Match ready ping sent to both captains.

[5] Match Completion & Result
    └── Judge runs /event-result → Enters scores + screenshots → Results posted to #results.

[6] Challonge Update
    └── Staff runs /upload-score → Match scores synced directly to Challonge bracket.

[7] VOD Upload
    └── Recorder runs /link add → Attaches stream VODs → Results embed updated live.

[8] Channel Archival
    └── Staff runs $close → HTML & TXT transcripts generated → Uploaded to #transcripts → Room archived.
```
