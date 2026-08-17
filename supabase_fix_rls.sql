-- =========================================================================
-- SUPABASE ROW LEVEL SECURITY (RLS) FIX
-- Run this in your Supabase SQL Editor to allow the web dashboard
-- and Discord bot to read, write, and sync GuildConfig, logos, and brackets.
-- =========================================================================

-- Disable RLS on core tournament tables so bot & dashboard API keys can read/write
ALTER TABLE IF EXISTS "GuildConfig" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Tournaments" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Events" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Results" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Challonge_Uploads" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "JudgeAssignments" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "StaffStats" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Deadlines" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "WebUsers" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "TournamentSponsors" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "AffiliateProducts" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "SponsorClickLogs" DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "ActivityLogs" DISABLE ROW LEVEL SECURITY;

-- Ensure server_logo_path and server_logo_url columns exist in GuildConfig
ALTER TABLE IF EXISTS "GuildConfig" ADD COLUMN IF NOT EXISTS "server_logo_path" TEXT;
ALTER TABLE IF EXISTS "GuildConfig" ADD COLUMN IF NOT EXISTS "server_logo_url" TEXT;
