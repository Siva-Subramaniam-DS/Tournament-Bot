-- =========================================================================================
-- CREATE BANNED PLAYERS TABLE FOR TOURNAMENT BOT
-- Run this in your Supabase project SQL Editor
-- =========================================================================================

CREATE TABLE IF NOT EXISTS public.banned_players (
    game_id TEXT PRIMARY KEY,
    discord_user_id TEXT,
    discord_username TEXT,
    reason TEXT DEFAULT 'Tournament Ban',
    banned_by TEXT,
    banned_at TIMESTAMPTZ DEFAULT NOW(),
    guild_id TEXT
);

-- Index for fast game_id queries (case-insensitive search)
CREATE INDEX IF NOT EXISTS idx_banned_players_game_id ON public.banned_players (LOWER(game_id));
CREATE INDEX IF NOT EXISTS idx_banned_players_discord_id ON public.banned_players (discord_user_id);

-- Enable RLS and grant access
ALTER TABLE public.banned_players ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow select on banned_players" ON public.banned_players;
CREATE POLICY "Allow select on banned_players"
ON public.banned_players FOR SELECT
TO anon, authenticated, service_role
USING (true);

DROP POLICY IF EXISTS "Allow all on banned_players" ON public.banned_players;
CREATE POLICY "Allow all on banned_players"
ON public.banned_players FOR ALL
TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);
