-- One-time migration: make tournament IDs unique per Discord guild.
-- Run this in Supabase SQL Editor before deploying the corresponding code.
-- It preserves existing tournament and match rows.

BEGIN;

ALTER TABLE "Tournaments"
    ADD COLUMN IF NOT EXISTS "Guild_ID" TEXT;

ALTER TABLE "Matches"
    ADD COLUMN IF NOT EXISTS "Guild_ID" TEXT;

-- Existing tournament IDs were globally unique, so this backfill is unambiguous.
UPDATE "Matches" AS match_row
SET "Guild_ID" = tournament_row."Guild_ID"
FROM "Tournaments" AS tournament_row
WHERE match_row."Guild_ID" IS NULL
  AND match_row."Tournament_ID" = tournament_row."Tournament_ID";

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM "Tournaments"
        WHERE "Guild_ID" IS NULL OR btrim("Guild_ID") = ''
    ) THEN
        RAISE EXCEPTION 'Cannot scope tournaments: every Tournaments row needs a Guild_ID.';
    END IF;
END $$;

-- The current update schema deliberately has no tournament foreign keys on
-- Matches. CASCADE removes a legacy single-column FK if one still exists.
ALTER TABLE "Tournaments"
    DROP CONSTRAINT IF EXISTS "Tournaments_pkey" CASCADE;

ALTER TABLE "Tournaments"
    ALTER COLUMN "Guild_ID" SET NOT NULL,
    ALTER COLUMN "Tournament_ID" SET NOT NULL,
    ADD CONSTRAINT "Tournaments_pkey" PRIMARY KEY ("Guild_ID", "Tournament_ID");

CREATE INDEX IF NOT EXISTS "Matches_Guild_ID_Tournament_ID_idx"
    ON "Matches" ("Guild_ID", "Tournament_ID");

COMMIT;
