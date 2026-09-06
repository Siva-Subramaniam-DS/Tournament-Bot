-- =========================================================================
-- SUPABASE TABLE SCHEMA UPDATE QUERIES (NON-DESTRUCTIVE / SAFE TO RUN)
-- Run this in your Supabase SQL Editor to ensure all tables & columns exist.
-- =========================================================================

-- 1. Table: GuildConfig
CREATE TABLE IF NOT EXISTS "GuildConfig" (
    "Guild_ID" TEXT PRIMARY KEY
);

ALTER TABLE "GuildConfig"
    ADD COLUMN IF NOT EXISTS "Admin_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Organizer_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Helper_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Judge_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Recorder_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Staff_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Players_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Challonge_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Organization_Name" TEXT,
    ADD COLUMN IF NOT EXISTS "Tournament_System_Name" TEXT,
    ADD COLUMN IF NOT EXISTS "organization_name" TEXT,
    ADD COLUMN IF NOT EXISTS "tournament_system_name" TEXT,
    ADD COLUMN IF NOT EXISTS "server_logo_path" TEXT,
    ADD COLUMN IF NOT EXISTS "server_logo_url" TEXT,
    ADD COLUMN IF NOT EXISTS "player_info_link" TEXT,
    ADD COLUMN IF NOT EXISTS "player_info_format" TEXT,
    ADD COLUMN IF NOT EXISTS "google_sheet_link" TEXT,
    ADD COLUMN IF NOT EXISTS "Challonge_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Transcript_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Closed_Category_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Schedule_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Results_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "channel_bracket" TEXT,
    ADD COLUMN IF NOT EXISTS "Bot_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Thumbnail_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now());

-- 2. Table: Tournaments
CREATE TABLE IF NOT EXISTS "Tournaments" (
    "Guild_ID" TEXT NOT NULL,
    "Tournament_ID" TEXT NOT NULL,
    PRIMARY KEY ("Guild_ID", "Tournament_ID")
);

ALTER TABLE "Tournaments"
    ADD COLUMN IF NOT EXISTS "Guild_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Tournament_Name" TEXT,
    ADD COLUMN IF NOT EXISTS "Game" TEXT,
    ADD COLUMN IF NOT EXISTS "State" TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS "Key" TEXT,
    ADD COLUMN IF NOT EXISTS "Challonge_Bracket_Link" TEXT,
    ADD COLUMN IF NOT EXISTS "challonge_bracket_link" TEXT,
    ADD COLUMN IF NOT EXISTS "Google_Sheet_Link" TEXT,
    ADD COLUMN IF NOT EXISTS "Captains_Sheet_Link" TEXT,
    ADD COLUMN IF NOT EXISTS "Sheet_Link" TEXT,
    ADD COLUMN IF NOT EXISTS "Attendance_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Transcript_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Schedule_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Rules_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Result_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Deadline_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Challonge_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Transcript_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Bot_Logs_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Thumbnail_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Participant_Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Closed_Ticket_Category_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Closed_Ticket_Category_2_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Open_Category_1_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Open_Category_2_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Open_Category_3_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Open_Category_4_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Auto_Room_Creation" BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS "Players_Role_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Map_Pool" TEXT DEFAULT 'New Storm (2024), Arid Frontier, Islands of Iceland, Unexplored Rocks, Arctic, Lost City, Polar Frontier, Hidden Dragon, Monstrous Maelstrom, Two Samurai, Stone Peaks, Viking Bay, Rising Fortress, Greenlands, Old Storm',
    ADD COLUMN IF NOT EXISTS "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now());

-- 3. Table: Matches
CREATE TABLE IF NOT EXISTS "Matches" (
    "Match_ID" TEXT PRIMARY KEY,
    "Guild_ID" TEXT,
    "Match_Name" TEXT,
    "Tournament_ID" TEXT,
    "Round" INTEGER,
    "Group" TEXT,
    "Team1_ID" TEXT,
    "Team2_ID" TEXT,
    "Team1_Score" INTEGER,
    "Team2_Score" INTEGER,
    "Status" TEXT DEFAULT 'scheduled',
    "Scheduled_Time" TIMESTAMP WITH TIME ZONE,
    "Channel_ID" TEXT,
    "recording_link" TEXT,
    "recorder_link" TEXT,
    "judge_link" TEXT,
    "results_message_id" TEXT,
    "results_channel_id" TEXT,
    "match_results_message_id" TEXT,
    "match_results_channel_id" TEXT,
    "Winner_ID" TEXT,
    "Remarks" TEXT,
    "Screenshots_Count" INTEGER DEFAULT 0,
    "Disqualified" BOOLEAN DEFAULT FALSE,
    "Created_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

ALTER TABLE "Matches"
    ADD COLUMN IF NOT EXISTS "Guild_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Match_Name" TEXT,
    ADD COLUMN IF NOT EXISTS "Tournament_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Round" INTEGER,
    ADD COLUMN IF NOT EXISTS "Group" TEXT,
    ADD COLUMN IF NOT EXISTS "Team1_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Team2_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Team1_Score" INTEGER,
    ADD COLUMN IF NOT EXISTS "Team2_Score" INTEGER,
    ADD COLUMN IF NOT EXISTS "Status" TEXT DEFAULT 'scheduled',
    ADD COLUMN IF NOT EXISTS "Scheduled_Time" TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS "Channel_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "recording_link" TEXT,
    ADD COLUMN IF NOT EXISTS "recorder_link" TEXT,
    ADD COLUMN IF NOT EXISTS "judge_link" TEXT,
    ADD COLUMN IF NOT EXISTS "results_message_id" TEXT,
    ADD COLUMN IF NOT EXISTS "results_channel_id" TEXT,
    ADD COLUMN IF NOT EXISTS "match_results_message_id" TEXT,
    ADD COLUMN IF NOT EXISTS "match_results_channel_id" TEXT,
    ADD COLUMN IF NOT EXISTS "Winner_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Remarks" TEXT,
    ADD COLUMN IF NOT EXISTS "Screenshots_Count" INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS "Disqualified" BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now());

-- Remove foreign key constraints on Matches so matches save freely without requiring pre-existing Teams rows
ALTER TABLE "Matches" DROP CONSTRAINT IF EXISTS "Matches_Team1_ID_fkey";
ALTER TABLE "Matches" DROP CONSTRAINT IF EXISTS "Matches_Team2_ID_fkey";
ALTER TABLE "Matches" DROP CONSTRAINT IF EXISTS "Matches_Tournament_ID_fkey";

-- 4. Table: MatchStaff
CREATE TABLE IF NOT EXISTS "MatchStaff" (
    "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    "Match_ID" TEXT NOT NULL,
    "User_ID" TEXT NOT NULL,
    "Name" TEXT,
    "Role" TEXT NOT NULL,
    "Confirmed" BOOLEAN DEFAULT FALSE,
    "Confirmed_At" TIMESTAMP WITH TIME ZONE,
    "Claimed_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    UNIQUE ("Match_ID", "User_ID", "Role")
);

-- 5. Table: StaffStats
CREATE TABLE IF NOT EXISTS "StaffStats" (
    "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    "Guild_ID" TEXT NOT NULL,
    "User_ID" TEXT NOT NULL,
    "Name" TEXT,
    "Judge_Count" INTEGER DEFAULT 0,
    "Recorder_Count" INTEGER DEFAULT 0,
    "Total_Count" INTEGER DEFAULT 0,
    "Timestamp" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- Ensure UNIQUE constraint on (Guild_ID, User_ID) for StaffStats upsert
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'StaffStats_Guild_ID_User_ID_key'
    ) THEN
        ALTER TABLE "StaffStats" ADD CONSTRAINT "StaffStats_Guild_ID_User_ID_key" UNIQUE ("Guild_ID", "User_ID");
    END IF;
EXCEPTION
    WHEN OTHERS THEN NULL;
END $$;

-- 6. Table: Deadlines
CREATE TABLE IF NOT EXISTS "Deadlines" (
    "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    "Tournament_ID" TEXT,
    "Guild_ID" TEXT,
    "Round" INTEGER,
    "Deadline_Time" TIMESTAMP WITH TIME ZONE NOT NULL,
    "Created_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

ALTER TABLE "Deadlines"
    ADD COLUMN IF NOT EXISTS "Tournament_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Guild_ID" TEXT,
    ADD COLUMN IF NOT EXISTS "Round" INTEGER,
    ADD COLUMN IF NOT EXISTS "Deadline_Time" TIMESTAMP WITH TIME ZONE;

-- 7. Tables: Teams & Players
CREATE TABLE IF NOT EXISTS "Teams" (
    "Team_ID" TEXT PRIMARY KEY,
    "Tournament_ID" TEXT,
    "Team_Name" TEXT NOT NULL,
    "Captain_ID" TEXT,
    "Captain_IGN" TEXT,
    "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS "Players" (
    "Player_ID" TEXT PRIMARY KEY,
    "Team_ID" TEXT,
    "Discord_ID" TEXT,
    "IGN" TEXT,
    "Game_ID" TEXT,
    "Title" TEXT,
    "Updated_At" TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 8. Fallback legacy tables (if legacy queries run)
CREATE TABLE IF NOT EXISTS "Events" (
    "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    "Event_ID" TEXT,
    "Guild_ID" TEXT,
    "Match_Name" TEXT,
    "Tournament" TEXT,
    "Round" TEXT,
    "Group" TEXT,
    "Date" TEXT,
    "UTC_Time" TEXT,
    "Team1_Captain_ID" TEXT,
    "Team1_Captain_Name" TEXT,
    "Team2_Captain_ID" TEXT,
    "Team2_Captain_Name" TEXT,
    "Judge_ID" TEXT,
    "Judge_Name" TEXT,
    "Recorder_ID" TEXT,
    "Recorder_Name" TEXT,
    "Channel_ID" TEXT,
    "Status" TEXT,
    "recording_link" TEXT,
    "recorder_link" TEXT,
    "judge_link" TEXT,
    "results_message_id" TEXT,
    "results_channel_id" TEXT,
    "Created_By_ID" TEXT,
    "Created_By_Name" TEXT,
    "Timestamp" TEXT
);

CREATE TABLE IF NOT EXISTS "Results" (
    "id" BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    "Event_ID" TEXT,
    "Guild_ID" TEXT,
    "Match_Name" TEXT,
    "Tournament" TEXT,
    "Round" TEXT,
    "Group" TEXT,
    "Winner_ID" TEXT,
    "Winner_Name" TEXT,
    "Winner_Score" TEXT,
    "Loser_ID" TEXT,
    "Loser_Name" TEXT,
    "Loser_Score" TEXT,
    "Judge_ID" TEXT,
    "Judge_Name" TEXT,
    "Recorder_ID" TEXT,
    "Recorder_Name" TEXT,
    "Remarks" TEXT,
    "Screenshots_Count" INTEGER DEFAULT 0,
    "Disqualified" BOOLEAN DEFAULT FALSE,
    "Timestamp" TEXT
);
