-- =========================================================================
-- SUPABASE DATABASE & COLUMN FIX
-- Run this in your Supabase SQL Editor to ensure all tables, columns,
-- and permissions are configured for server logos and tournaments.
-- =========================================================================

-- 1. Disable Row Level Security (RLS) so bot and API keys can read/write
ALTER TABLE IF EXISTS "GuildConfig" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Tournaments" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Events" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Results" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Challonge_Uploads" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "JudgeAssignments" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "StaffStats" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Deadlines" DISABLE ROW LEVEL SECURITY;

-- 2. Ensure server logo columns exist in GuildConfig table
ALTER TABLE IF EXISTS "GuildConfig" ADD COLUMN IF NOT EXISTS "server_logo_path" TEXT;
ALTER TABLE IF EXISTS "GuildConfig" ADD COLUMN IF NOT EXISTS "server_logo_url" TEXT;

-- 3. Ensure Game column exists in Tournaments table
ALTER TABLE IF EXISTS "Tournaments" ADD COLUMN IF NOT EXISTS "Game" TEXT;
ALTER TABLE IF EXISTS "Tournaments" ADD COLUMN IF NOT EXISTS "game" TEXT;
