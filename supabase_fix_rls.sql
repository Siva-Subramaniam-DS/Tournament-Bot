-- =========================================================================
-- SUPABASE ROW LEVEL SECURITY (RLS) FIX & DATABASE SECURITY
-- Run this in your Supabase SQL Editor to enable RLS on all tables.
-- 
-- Why this works:
-- 1. Your Discord bot uses the SUPABASE_SERVICE_ROLE_KEY in .env,
--    which automatically BYPASSES Row Level Security (full read/write access).
-- 2. Enabling RLS blocks unauthorized public/anon users from reading or
--    deleting your tables via the public API, satisfying Supabase security audits.
-- =========================================================================

-- 1. Enable Row Level Security (RLS) on all tournament & bot tables
ALTER TABLE IF EXISTS "GuildConfig" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Tournaments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Matches" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Results" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Challonge_Uploads" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "JudgeAssignments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "StaffStats" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "Deadlines" ENABLE ROW LEVEL SECURITY;

-- 2. Enable RLS on Web Portal & Extended tables
ALTER TABLE IF EXISTS "WebUsers" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "TournamentSponsors" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "AffiliateProducts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "SponsorClickLogs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "ActivityLogs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS "CommandConfigs" ENABLE ROW LEVEL SECURITY;

-- 3. Dynamic block to automatically enable RLS on EVERY table in public schema
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', r.tablename);
    END LOOP;
END $$;

